#!/usr/bin/env python
#
#    Copyright (c) 2009, 2010, 2011 Tom Keffer <tkeffer@gmail.com>
#
#    See the file LICENSE.txt for your full rights.
#
#    $Revision$
#    $Author$
#    $Date$
#
"""Configure various resources used by weewx"""

import sys
import syslog
import os.path
from optparse import OptionParser
import configobj

import user.extensions
import weewx.archive
import weewx.stats
import weewx.VantagePro

usagestr = """%prog: config_path [Options]

Configuration program for the weewx weather system.

Arguments:
    config_path: Path to the configuration file to be used."""

def main():
    parser = OptionParser(usage=usagestr)
    parser.add_option("--create-database",  action="store_true", dest="create_database",  help="To create the main database archive")
    parser.add_option("--create-stats",     action="store_true", dest="create_stats",     help="To create the statistical database")
    parser.add_option("--backfill-stats",   action="store_true", dest="backfill_stats",   help="To backfill the statistical database from the main database")
    parser.add_option("--reconfig-database",action="store_true", dest="reconfig_database",help="To reconfigure the main database archive")
    parser.add_option("--configure-VantagePro", action="store_true", dest="configure_VP", help="To configure a VantagePro weather station")
    parser.add_option("--clear-VantagePro",     action="store_true", dest="clear_VP",     help="To clear the memory of the VantagePro weather station")
    
    (options, args) = parser.parse_args()
    
    if len(args) < 1:
        print "Missing argument(s)."
        print parser.parse_args(["--help"])
        sys.exit(weewx.CMD_ERROR)
    
    config_path = args[0]
    
    # Set defaults for the system logger:
    syslog.openlog('configure', syslog.LOG_PID|syslog.LOG_CONS)
    
    # Try to open up the given configuration file. Declare an error if unable to.
    try :
        config_dict = configobj.ConfigObj(config_path, file_error=True)
    except IOError:
        print "Unable to open configuration file ", config_path
        syslog.syslog(syslog.LOG_CRIT, "main: Unable to open configuration file %s" % config_path)
        sys.exit(weewx.CONFIG_ERROR)
        
    if options.create_database:
        createMainDatabase(config_dict)
    
    if options.create_stats:
        createStatsDatabase(config_dict)
        
    if options.backfill_stats:
        backfillStatsDatabase(config_dict)

    if options.reconfig_database:
        reconfigMainDatabase(config_dict)
            
    if options.configure_VP:
        configureVP(config_dict)

    if options.clear_VP:
        clearVP(config_dict)

def createMainDatabase(config_dict):
    """Create the main weewx archive database"""
    # Open up the main database archive
    archiveFilename = os.path.join(config_dict['Station']['WEEWX_ROOT'], 
                                   config_dict['Archive']['archive_file'])
    try:
        dummy_archive = weewx.archive.Archive(archiveFilename)
    except StandardError:
        # Configure it
        weewx.archive.config(archiveFilename)
        print "Created archive database %s" % archiveFilename
    else:
        print "The archive database %s already exists" % archiveFilename

def createStatsDatabase(config_dict):
    """Create the weewx statistical database"""
    # Open up the Stats database
    statsFilename = os.path.join(config_dict['Station']['WEEWX_ROOT'], 
                                 config_dict['Stats']['stats_file'])
    try:
        dummy_statsDb = weewx.stats.StatsDb(statsFilename)
    except StandardError:
        # Configure it:
        weewx.stats.config(statsFilename, config_dict['Stats'].get('stats_types'))
        print "Created statistical database %s" % statsFilename
    else:
        print "The statistical database %s already exists" % statsFilename

def backfillStatsDatabase(config_dict):
    """Use the main archive database to backfill the stats database."""

    # Configure if necessary. This will do nothing if the database
    # has already been configured:
    createStatsDatabase(config_dict)

    # Open up the Stats database
    statsFilename = os.path.join(config_dict['Station']['WEEWX_ROOT'], 
                                 config_dict['Stats']['stats_file'])
    statsDb = weewx.stats.StatsDb(statsFilename)
    
    # Open up the main database archive
    archiveFilename = os.path.join(config_dict['Station']['WEEWX_ROOT'], 
                                   config_dict['Archive']['archive_file'])
    archive = weewx.archive.Archive(archiveFilename)

    # Now backfill
    weewx.stats.backfill(archive, statsDb)
    print "Backfilled statistical database %s with archive data from %s" % (statsFilename, archiveFilename)
    
def reconfigMainDatabase(config_dict):
    """Change the schema of the old database"""
    
    # The old archive:
    oldArchiveFilename = os.path.join(config_dict['Station']['WEEWX_ROOT'], 
                                      config_dict['Archive']['archive_file'])
    newArchiveFilename = oldArchiveFilename + ".new"
    weewx.archive.reconfig(oldArchiveFilename, newArchiveFilename)
    
def configureVP(config_dict):
    """Configure a VantagePro as per the configuration file."""
    
    print "Configuring VantagePro..."
    # Open up the weather station:
    station = weewx.VantagePro.VantagePro(**config_dict['VantagePro'])

    old_archive_interval = station.archive_interval
    new_archive_interval = config_dict['VantagePro'].as_int('archive_interval')
    
    if old_archive_interval == new_archive_interval:
        print "Old archive interval matches new archive interval (%d seconds). Nothing done" % old_archive_interval
    else:
        print "VantagePro old archive interval is %d seconds, new one is %d" % (old_archive_interval, new_archive_interval)
        print "Proceeding will erase old archive records."
        ans = raw_input("Are you sure you want to proceed? (y/n) ")
        if ans == 'y' :
            station.setArchiveInterval(new_archive_interval)
            print "Archive interval now set to %d." % (new_archive_interval,)
            # The Davis documentation implies that the log is cleared after
            # changing the archive interval, but that doesn't seem to be the
            # case. Clear it explicitly:
            station.clearLog()
            print "Archive records cleared."
        else:
            print "Nothing done."
            
def clearVP(config_dict):
    """Clear the archive memory of a VantagePro"""
    
    print "Clearing the archive memory of the VantagePro..."
    # Open up the weather station:
    station = weewx.VantagePro.VantagePro(**config_dict['VantagePro'])
    print "Proceeding will erase old archive records."
    ans = raw_input("Are you sure you wish to proceed? (y/n) ")
    if ans == 'y':
        station.clearLog()
        print "Archive records cleared."
    else:
        print "Nothing done."

main()
