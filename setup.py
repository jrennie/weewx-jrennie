#!/usr/bin/env python
#
#    weewx --- A simple, high-performance weather station server
#
#    Copyright (c) 2009 Tom Keffer <tkeffer@gmail.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#    Revision: $Rev$
#    Author:   $Author$
#    Date:     $Date$
#
""" Customized weewx setup script.

    In addition to the normal setup script duties, this script does the
    following:

 1. When building a source distribution ('sdist') it filters out username
    and password information from the configuration file weewx.conf

 2. It merges any existing weewx.conf configuration files into the new, thus
    preserving any user changes.
    
 3. It sets the option ['Station']['WEEWX_ROOT'] in weewx.conf to reflect
    the actual installation directory (as set in setup.cfg or specified
    in the command line to setup.py install)

 4. It backups up any pre-existing template subdirectory
"""

from distutils.core import setup, Command
from distutils.command.install_data import install_data
from distutils.command.sdist import sdist
from distutils import log
import os
import os.path
import re
import time
import tempfile
import shutil
import configobj

from weewx import __version__ as VERSION

class My_install_data(install_data):
    """Specialized version of install_data 
    
    This version: 
    
      - Sets WEEWX_ROOT in the configuration file to reflect the
        actual installation root directory;
      - Merges an old configuration file into a new,
        thus preserving any changes made by the user;
      - Massages the daemon start up script to reflect the choice
        of WEEWX_ROOT        
    """
    
    def copy_file(self, f, install_dir, **kwargs):
        rv = None
        # If this is the configuration file, then merge it instead
        # of copying it
        if f == 'weewx.conf':
            rv = self.massageConfigFile(f, install_dir, **kwargs)
        elif f == 'start_scripts/Debian/weewx':
            rv = self.massageStartFile(f, install_dir, **kwargs)
        else:
            rv = install_data.copy_file(self, f, install_dir, **kwargs)
        return rv
    
    def run(self):
        template_dir = os.path.join(self.install_dir, 'templates')
        if os.path.exists(template_dir):
            backupdir = backup(template_dir)
            print "Backed up template subdirectory to %s" % backupdir
        install_data.run(self)
        
    def massageConfigFile(self, f, install_dir, **kwargs):
        """Merges any old config file into the new one, and sets WEEWX_ROOT
        
        If an old configuration file exists, it will merge the contents
        into the new file. It also sets variable ['Station']['WEEWX_ROOT']
        to reflect the installation directory"""
        
        # The path name of the final output file:
        outname = os.path.join(install_dir, os.path.basename(f))
        
        # Create a ConfigObj using the new contents:
        newconfig = configobj.ConfigObj(f)
        newconfig.indent_type = '    '
        
        # Check to see if there is an existing config file.
        # If so, merge its contents with the new one
        if os.path.exists(outname):
            oldconfig = configobj.ConfigObj(outname)
            # Any user changes in oldconfig will overwrite values in newconfig
            # with this merge
            newconfig.merge(oldconfig)

        # Make sure WEEWX_ROOT reflects the choice made in setup.cfg:
        newconfig['Station']['WEEWX_ROOT'] = self.install_dir
        
        # Get a temporary file:
        tmpfile = tempfile.NamedTemporaryFile("w", 1)
        
        # Write the new configuration file to it:
        newconfig.write(tmpfile)
        
        # Back up the old config file if it exists:
        if os.path.exists(outname):
            backup_path = backup(outname)
            print "Backed up old configuration file as %s" % backup_path
            
        # Now install the temporary file (holding the merged config data)
        # into the proper place:
        rv = install_data.copy_file(self, tmpfile.name, outname, **kwargs)
        
        # Set the permission bits unless this is a dry run:
        if not self.dry_run:
            shutil.copymode(f, outname)

        return rv
        
    def massageStartFile(self, f, install_dir, **kwargs):

        outname = os.path.join(install_dir, os.path.basename(f))
        sre = re.compile(r"WEEWX_ROOT\s*=")

        infile = open(f, "r")
        tmpfile = tempfile.NamedTemporaryFile("w", 1)
        
        for line in infile:
            if sre.match(line):
                tmpfile.writelines("WEEWX_ROOT=%s\n" % self.install_dir)
            else:
                tmpfile.writelines(line)
        
        rv = install_data.copy_file(self, tmpfile.name, outname, **kwargs)

        # Set the permission bits unless this is a dry run:
        if not self.dry_run:
            shutil.copymode(f, outname)

        return rv

def backup(filepath):
    newpath = filepath + time.strftime(".%Y%m%d%H%M%S")
    os.rename(filepath, newpath)
    return newpath

class My_sdist(sdist):
    """Specialized version of sdist which does not include password information in distribution

    See http://epydoc.sourceforge.net/stdlib/distutils.command.sdist.sdist-class.html
    for possible sdist instance methods."""

    def copy_file(self, f, install_dir, **kwargs):
        """Specialized version of copy_file.

        Return a tuple (dest_name, copied): 'dest_name' is the actual name of
        the output file, and 'copied' is true if the file was copied (or would
        have been copied, if 'dry_run' true)."""
        # If this is the configuration file, then massage it to eliminate
        # the password info
        if f == 'weewx.conf':
            # Should have a more useful logging message than this!
            config = configobj.ConfigObj(f)
            config.indent_type = '    '
            try:
                config['FTP']['user'] = """replace with your username"""
                config['FTP']['password'] = """replace with your password"""
                config['FTP']['server'] = """replace with your server name, eg, www.threefools.org"""
                config['FTP']['path'] = """replace with the destination root directory on your server"""
                print config['FTP']['user']
                print config['FTP']['password']
                print config['FTP']['server']
                log.info("%s %s -> %s", 'filtering', f, install_dir)
            except KeyError:
                pass
            try:
                config['Wunderground']['station'] = " (replace with your Weather Underground station name)"
                config['Wunderground']['password'] = "(replace with your password)"
            except KeyError:
                pass
            if not self.dry_run:
                outfile = open(install_dir, 'w')
                config.write(outfile)
                outfile.close()
            return (install_dir, True)
        else :
            return sdist.copy_file(self, f, install_dir, **kwargs)

setup(name='weewx',
      version=VERSION,
      description='The weewx weather system',
      long_description="The weewx weather system manages a Davis VantagePro "
      "weather station. It generates plots, statistics, and HTML pages of the "
      "current and historical weather",
      author='Tom Keffer',
      author_email='tkeffer@gmail.com',
      url='http://www.threefools.org/weewx',
      packages    = ['weewx', 'weeplot', 'weeutil'],
      py_modules  = ['upload', 'daemon'],
      scripts     = ['configure.py', 'weewxd.py'],
      data_files  = [('',                        ['CHANGES.txt', 'LICENSE.txt', 'README', 'readme.htm', 'weewx.conf']), 
                     ('templates',               ['templates/index.tmpl', 'templates/week.tmpl',
                                                  'templates/month.tmpl', 'templates/year.tmpl',
                                                  'templates/NOAA_month.tmpl', 'templates/NOAA_year.tmpl']), 
                     ('public_html',             ['public_html/weewx.css']),
                     ('public_html/backgrounds', ['public_html/backgrounds/band.gif',
                                                  'public_html/backgrounds/butterfly.jpg',
                                                  'public_html/backgrounds/drops.gif',
                                                  'public_html/backgrounds/flower.jpg',
                                                  'public_html/backgrounds/leaf.jpg',
                                                  'public_html/backgrounds/night.gif']),
                     ('start_scripts/Debian',    ['start_scripts/Debian/weewx'])],
      requires    = ['configobj', 'pyserial(>=1.35)', 'Cheetah(>=2.0)', 'pysqlite(>=2.5)', 'PIL(>=1.1.6)'],
      cmdclass    = {"install_data" : My_install_data,
                     "sdist" :        My_sdist}
      )
