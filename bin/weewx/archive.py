#
#    Copyright (c) 2009, 2010, 2011 Tom Keffer <tkeffer@gmail.com>
#
#    See the file LICENSE.txt for your full rights.
#
#    $Revision$
#    $Author$
#    $Date$
#
"""Classes and functions for interfacing with a weewx sqlite3 archive."""
from __future__ import with_statement
import syslog
import os.path
import math
from pysqlite2 import dbapi2 as sqlite3
    
import weewx.units
import weeutil.weeutil
import weeutil.dbutil

#===============================================================================
#                         class Archive
#===============================================================================

class Archive(object):
    """Manages a sqlite archive file. Offers a number of convenient member functions
    for managing the archive file. These functions encapsulate whatever sql statements
    are needed."""
    
    def __init__(self, archiveFilename):
        """Initialize an object of type weewx.Archive. 
        
        If the database does not exist or it is uninitialized, an
        exception will be thrown. 
        
        archiveFilename: The path to the sqlite3 archive file.
        """
        self.archiveFilename = archiveFilename
        self.sqlkeys = self._getTypes()
    
    def lastGoodStamp(self):
        """Retrieves the epoch time of the last good archive record.
        
        returns: Time of the last good archive record as an epoch time, or
        None if there are no records."""
        _row = self.getSql("SELECT MAX(dateTime) FROM archive")
        return _row[0]
    
    def firstGoodStamp(self):
        """Retrieves earliest timestamp in the archive.
        
        returns: Time of the first good archive record as an epoch time, or
        None if there are no records."""
        _row = self.getSql("SELECT MIN(dateTime) FROM archive")
        return _row[0]

    def addRecord(self, record_obj):
        """Commit a single record or a collection of records to the archive.
        
        record_obj: Either a data record, or an iterable that can return data
        records. Each data record must look like a dictionary, where the keys
        are the SQL types and the values are the values to be stored in the
        database."""
        
        # Determine if record_obj is just a single dictionary instance (in which
        # case it will have method 'keys'). If so, wrap it in something iterable
        # (a list):
        record_list = [record_obj] if hasattr(record_obj, 'keys') else record_obj

        with sqlite3.connect(self.archiveFilename) as _connection:

            for record in record_list:

                if record['dateTime'] is None:
                    syslog.syslog(syslog.LOG_ERR, "Archive: archive record with null time encountered. Ignored.")
                    continue
        
                # Only data types that appear in the database schema can be inserted.
                # To find them, form the intersection between the set of all record
                # keys and the set of all sql keys
                record_key_set = set(record.keys())
                insert_key_set = record_key_set.intersection(self.sqlkeys)
                # Convert to an ordered list:
                key_list = list(insert_key_set)
                # Get the values in the same order:
                value_list = [record[k] for k in key_list]
                
                # This will a string of sql types, separated by commas
                k_str = ','.join(key_list)
                # This will be a string with the correct number of placeholder question marks:
                q_str = ','.join('?' * len(key_list))
                # Form the SQL insert statement:
                sql_insert_stmt = "INSERT INTO archive (%s) VALUES (%s)" % (k_str, q_str) 
                try:
                    _connection.execute(sql_insert_stmt, value_list)
                    syslog.syslog(syslog.LOG_NOTICE, "Archive: added archive record %s" % weeutil.weeutil.timestamp_to_string(record['dateTime']))
                except Exception, e:
                    syslog.syslog(syslog.LOG_ERR, "Archive: unable to add archive record %s" % weeutil.weeutil.timestamp_to_string(record['dateTime']))
                    syslog.syslog(syslog.LOG_ERR, " ****    Reason: %s" % e)

    def genBatchRecords(self, startstamp, stopstamp):
        """Generator function that yields ValueRecords within a time interval.
        
        startstamp: Exclusive start of the interval in epoch time. If 'None', then
        start at earliest archive record.
        
        stopstamp: Inclusive end of the interval in epoch time. If 'None', then
        end at last archive record.
        
        yields: A dictionary for each time or None if there is no 
        record at that time. """
        _connection = sqlite3.connect(self.archiveFilename)
        _connection.row_factory = sqlite3.Row
        _cursor=_connection.cursor()
        try:
            if startstamp is None:
                if stopstamp is None:
                    _cursor.execute("SELECT * FROM archive")
                else:
                    _cursor.execute("SELECT * from archive where dateTime <= ?", (stopstamp,))
            else:
                if stopstamp is None:
                    _cursor.execute("SELECT * from archive where dateTime > ?", (startstamp,))
                else:
                    _cursor.execute("SELECT * FROM archive WHERE dateTime > ? AND dateTime <= ?", (startstamp, stopstamp))
            
            for _row in _cursor :
                yield dict(zip(_row.keys(), _row)) if _row else None
        finally:
            _cursor.close()
            _connection.close()

    def getRecord(self, timestamp):
        """Get a single archive record with a given epoch time stamp.
        
        timestamp: The epoch time of the desired record.
        
        returns: a dictionary. Key is a sql type, value its value"""

        with sqlite3.connect(self.archiveFilename) as _connection:
            _connection.row_factory = sqlite3.Row
            _cursor = _connection.execute("SELECT * FROM archive WHERE dateTime=?;", (timestamp,))
            _row = _cursor.fetchone()

        return dict(zip(_row.keys(), _row)) if _row else None

    def getSql(self, sql, *sqlargs):
        """Executes an arbitrary SQL statement on the database.
        
        sql: The SQL statement
        
        sqlargs: The arguments for the SQL statement
        
        returns: an instance of sqlite3.Row
        """
        with sqlite3.connect(self.archiveFilename) as _connection:
            _connection.row_factory = sqlite3.Row
            _cursor = _connection.execute(sql, sqlargs)
            _row = _cursor.fetchone()
            return _row

    def genSql(self, sql, *sqlargs):
        """Generator function that executes an arbitrary SQL statement on the database."""
        _connection = sqlite3.connect(self.archiveFilename)
        _connection.row_factory = sqlite3.Row
        _cursor=_connection.cursor()
        try:
            _cursor.execute(sql, sqlargs)
            for _row in _cursor:
                yield _row
        finally:
            _cursor.close()
            _connection.close()

    def getSqlVectors(self, sql_type, startstamp, stopstamp,
                      aggregate_interval=None, 
                      aggregate_type=None):
        """Get time and (possibly aggregated) data vectors within a time interval. 
        
        The return value is a 2-way tuple. The first member is a vector of time
        values, the second member an instance of weewx.std_unit_system.Value with a
        value of a vector of data values, and a unit_type given by sql_type. 
        
        An example of a returned value is: (time_vec, Value(outTempVec, 'outTemp')). 
        
        If aggregation is desired (archive_interval is not None), then each element represents
        a time interval exclusive on the left, inclusive on the right. The time
        elements will all fall on the same local time boundary as startstamp. 
        For example, if startstamp is 8-Mar-2009 18:00
        and archive_interval is 10800 (3 hours), then the returned time vector will be
        (shown in local times):
        
        8-Mar-2009 21:00
        9-Mar-2009 00:00
        9-Mar-2009 03:00
        9-Mar-2009 06:00 etc.
        
        Note that DST happens at 02:00 on 9-Mar, so the actual time deltas between the
        elements is 3 hours between times #1 and #2, but only 2 hours between #2 and #3.
        
        NB: there is an algorithmic assumption here that the archive time interval
        is a constant.
        
        There is another assumption that the unit type does not change within a time interval.
        
        sql_type: The SQL type to be retrieved (e.g., 'outTemp') 
        
        startstamp: If aggregation_interval is None, then data with timestamps greater
        than or equal to this value will be returned. If aggregation_interval is not
        None, then the start of the first interval will be greater than (exclusive of) this
        value. 
        
        stopstamp: Records with time stamp less than or equal to this will be retrieved.
        If interval is not None, then the last interval will include this value.
        
        aggregate_interval: None if no aggregation is desired, otherwise
        this is the time interval over which a result will be aggregated.
        Default: None (no aggregation)
        
        aggregate_type: None if no aggregation is desired, otherwise the type of
        aggregation (e.g., 'sum', 'avg', etc.)  Required if aggregate_interval
        is non-None. Default: None (no aggregation)

        returns: a 2-way tuple of value tuples: 
          ((time_vec, time_unit_type), (data_vec, data_unit_type))
        The first element holds the time value tuple, the second the data value tuple.
        The first element of the time value tuple is a time vector (as a list), the
        second element the unit it is in ('unix_epoch'). The first element
        of the data value tuple is the data vector (as a list), the second
        element the unit type it is in. 
        """
        # There is an assumption here that the unit type does not change in the
        # middle of the time interval.

        time_vec = list()
        data_vec = list()
        std_unit_system = None
        _connection = sqlite3.connect(self.archiveFilename)
        _cursor=_connection.cursor()

        if aggregate_interval :
            if not aggregate_type:
                raise weewx.ViolatedPrecondition, "Aggregation type missing"
            sql_str = 'SELECT dateTime, %s(%s), usUnits FROM archive WHERE dateTime > ? AND dateTime <= ?' % (aggregate_type, sql_type)
            for stamp in weeutil.weeutil.intervalgen(startstamp, stopstamp, aggregate_interval):
                _cursor.execute(sql_str, stamp)
                _rec = _cursor.fetchone()
                # Don't accumulate any results where there wasn't a record
                # (signified by sqlite3 by a null key)
                if _rec:
                    if _rec[0] is not None:
                        time_vec.append(_rec[0])
                        data_vec.append(_rec[1])
                        if std_unit_system:
                            if std_unit_system != _rec[2]:
                                raise weewx.UnsupportedFeature, "Unit type cannot change within a time interval."
                        else:
                            std_unit_system = _rec[2]
        else:
            sql_str = 'SELECT dateTime, %s, usUnits FROM archive WHERE dateTime >= ? AND dateTime <= ?' % sql_type
            _cursor.execute(sql_str, (startstamp, stopstamp))
            for _rec in _cursor:
                assert(_rec[0])
                time_vec.append(_rec[0])
                data_vec.append(_rec[1])
                if std_unit_system:
                    if std_unit_system != _rec[2]:
                        raise weewx.UnsupportedFeature, "Unit type cannot change within a time interval."
                else:
                    std_unit_system = _rec[2]

        _cursor.close()
        _connection.close()

        time_unit_type = weewx.units.getStandardUnitType(std_unit_system, 'dateTime')
        data_unit_type = weewx.units.getStandardUnitType(std_unit_system, sql_type, aggregate_type)
        return ((time_vec, time_unit_type), (data_vec, data_unit_type))

    def getSqlVectorsExtended(self, ext_type, startstamp, stopstamp, 
                              aggregate_interval = None, 
                              aggregate_type = None):
        """Get time and (possibly aggregated) data vectors within a time interval.
        
        This function is very similar to getSqlVectors, except that for special types
        'windvec' and 'windgustvec', it returns wind data broken down into 
        its x- and y-components.
        
        sql_type: The SQL type to be retrieved (e.g., 'outTemp', or 'windvec'). 
        If this type is the special types 'windvec', or 'windgustvec', then what
        will be returned is a vector of complex numbers. 
        
        startstamp: If aggregation_interval is None, then data with timestamps greater
        than or equal to this value will be returned. If aggregation_interval is not
        None, then the start of the first interval will be greater than (exclusive of) this
        value. 
        
        stopstamp: Records with time stamp less than or equal to this will be retrieved.
        If interval is not None, then the last interval will include this value.
        
        aggregate_interval: None if no aggregation is desired, otherwise
        this is the time interval over which a result will be aggregated.
        Default: None (no aggregation)
        
        aggregate_type: None if no aggregation is desired, otherwise the type of
        aggregation (e.g., 'sum', 'avg', etc.)  Required if aggregate_interval
        is non-None. Default: None (no aggregation)
        
        returns: a 2-way tuple of 2-way tuples: 
          ((time_vec, time_unit_type), (data_vec, data_unit_type))
        The first tuple hold the time information: the first element 
        is the time vector, the second the unit type of the time vector. 
        The second tuple holds the data information. The first element is
        the data vector, the second the unit type of the data vector.
        If sql_type is 'windvec' or 'windgustvec', the data
        vector will be a vector of types complex. The real part is the x-component
        of the wind, the imaginary part the y-component. 
        """

        windvec_types = {'windvec'     : ('windSpeed, windDir'),
                         'windgustvec' : ('windGust,  windGustDir')}
        
        # Check to see if the requested type is not 'windvec' or 'windgustvec'
        if ext_type not in windvec_types:
            # The type is not one of the extended wind types. Use the regular version:
            return self.getSqlVectors(ext_type, startstamp, stopstamp, aggregate_interval, aggregate_type)

        # It is an extended wind type. Prepare the lists that will hold the final results.
        time_vec = list()
        data_vec = list()
        std_unit_system = None
        _connection = sqlite3.connect(self.archiveFilename)
        _cursor=_connection.cursor()

        # Is aggregation requested?
        if aggregate_interval :
            # Aggregation is requested.
            # The aggregation should happen over the x- and y-components. Because they do
            # not appear in the database (only the magnitude and direction do) we cannot
            # do the aggregation in the SQL statement. We'll have to do it in Python.
            # Do we know how to do it?
            if aggregate_type not in ('sum', 'count', 'avg', 'max', 'min'):
                raise weewx.ViolatedPrecondition, "Aggregation type missing or unknown"
            
            # This SQL select string will select the proper wind types
            sql_str = 'SELECT dateTime, %s, usUnits FROM archive WHERE dateTime > ? AND dateTime <= ?' % windvec_types[ext_type]
            # Go through each aggregation interval, calculating the aggregation.
            for stamp in weeutil.weeutil.intervalgen(startstamp, stopstamp, aggregate_interval):

                mag_extreme = dir_at_extreme = None
                xsum = ysum = 0.0
                count = 0
                last_time = None
                
                _cursor.execute(sql_str, stamp)

                for _rec in _cursor:
                    (mag, dir) = _rec[1:3]

                    if mag is None:
                        continue

                    # A good direction is necessary unless the mag is zero:
                    if mag == 0.0  or dir is not None:
                        count += 1
                        last_time  = _rec[0]
                        if std_unit_system:
                            if std_unit_system != _rec[3]:
                                raise weewx.UnsupportedFeature, "Unit type cannot change within a time interval."
                        else:
                            std_unit_system = _rec[3]
                        
                        # Pick the kind of aggregation:
                        if aggregate_type == 'min':
                            if mag_extreme is None or mag < mag_extreme:
                                mag_extreme = mag
                                dir_at_extreme = dir
                        elif aggregate_type == 'max':
                            if mag_extreme is None or mag > mag_extreme:
                                mag_extreme = mag
                                dir_at_extreme = dir
                        else:
                            # No need to do the arithmetic if mag is zero.
                            # We also need a good direction
                            if mag > 0.0 and dir is not None:
                                xsum += mag * math.cos(math.radians(90.0 - dir))
                                ysum += mag * math.sin(math.radians(90.0 - dir))
                # We've gone through the whole interval. Was their any good data?
                if count:
                    # Record the time of the last good data point:
                    time_vec.append(last_time)
                    # Form the requested aggregation:
                    if aggregate_type in ('min', 'max'):
                        if dir_at_extreme is None:
                            # The only way direction can be zero with a non-zero count
                            # is if all wind velocities were zero
                            if weewx.debug:
                                assert(mag_extreme <= 1.0e-6)
                            x_extreme = y_extreme = 0.0
                        else:
                            x_extreme = mag_extreme * math.cos(math.radians(90.0 - dir_at_extreme))
                            y_extreme = mag_extreme * math.sin(math.radians(90.0 - dir_at_extreme))
                        data_vec.append(complex(x_extreme, y_extreme))
                    elif aggregate_type == 'sum':
                        data_vec.append(complex(xsum, ysum))
                    elif aggregate_type == 'count':
                        data_vec.append(count)
                    else:
                        # Must be 'avg'
                        data_vec.append(complex(xsum/count, ysum/count))
        else:
            # No aggregation desired. It's a lot simpler. Go get the
            # data in the requested time period
            # This SQL select string will select the proper wind types
            sql_str = 'SELECT dateTime, %s, usUnits FROM archive WHERE dateTime >= ? AND dateTime <= ?' % windvec_types[ext_type]
            _cursor.execute(sql_str, (startstamp, stopstamp))
            for _rec in _cursor:
                # Record the time:
                time_vec.append(_rec[0])
                if std_unit_system:
                    if std_unit_system != _rec[3]:
                        raise weewx.UnsupportedFeature, "Unit type cannot change within a time interval."
                else:
                    std_unit_system = _rec[3]
                # Break the mag and dir down into x- and y-components.
                (mag, dir) = _rec[1:3]
                if mag is None or dir is None:
                    data_vec.append(None)
                else:
                    x = mag * math.cos(math.radians(90.0 - dir))
                    y = mag * math.sin(math.radians(90.0 - dir))
                    if weewx.debug:
                        # There seem to be some little rounding errors that are driving
                        # my debugging crazy. Zero them out
                        if abs(x) < 1.0e-6 : x = 0.0
                        if abs(y) < 1.0e-6 : y = 0.0
                    data_vec.append(complex(x,y))
        _cursor.close()
        _connection.close()

        time_unit_type = weewx.units.getStandardUnitType(std_unit_system, 'dateTime')
        data_unit_type = weewx.units.getStandardUnitType(std_unit_system, ext_type, aggregate_type)
        return ((time_vec, time_unit_type), (data_vec, data_unit_type))

    def _getTypes(self):
        """Returns the types appearing in an archive database.
        
        returns: A list of types or None if the database has not been initialized."""
        
        # Get the schema dictionary:
        schema_dict = weeutil.dbutil.schema(self.archiveFilename)
        # Get the columns in the table
        column_dict = weeutil.dbutil.column_dict(schema_dict)
        # If there is no 'archive' table, the database has not been initialized
#        if not 'archive' in column_dict:
#            return None
        # Convert from unicode to strings
        column_names = [str(s) for s in column_dict['archive']]
        return column_names

def config(archiveFilename, archiveSchema=None):
    """Configure a database for use with weewx. This will create the initial schema
    if necessary."""

    # Check whether the database exists:
    if not os.path.exists(archiveFilename):
        # If it doesn't exist, create the parent directories
        archiveDirectory = os.path.dirname(archiveFilename)
        if not os.path.exists(archiveDirectory):
            syslog.syslog(syslog.LOG_NOTICE, "archive: making archive directory %s." % archiveDirectory)
            os.makedirs(archiveDirectory)

    # Check to see if it has already been configured. If it has, do
    # nothing. We're done.
    if weeutil.dbutil.schema(archiveFilename):
        return
    
    # If the user has not supplied a schema, use the default schema 
    if not archiveSchema:
        import user.schemas
        archiveSchema = user.schemas.defaultArchiveSchema
        
    # List comprehension of the types, joined together with commas:
    _sqltypestr = ', '.join([' '.join(type) for type in archiveSchema])
    
    _createstr ="CREATE TABLE archive (%s);" % _sqltypestr

    with sqlite3.connect(archiveFilename) as _connection:
        _connection.execute(_createstr)
    
    syslog.syslog(syslog.LOG_NOTICE, "archive: created schema for archive file %s." % archiveFilename)

def reconfig(oldArchiveFilename, newArchiveFilename):
    """Copy over an old archive file to a new one, using the new schema."""

    config(newArchiveFilename)
    
    oldArchive = Archive(oldArchiveFilename)
    newArchive = Archive(newArchiveFilename)
    # This is very fast because it is done in a single transaction context:
    newArchive.addRecord(oldArchive.genBatchRecords(None,None))
