# sinks.py
# Jacob Hummel
"""
Classes and routines for analyzing sink data output by gadget.
"""
import os
import sys
import warnings
import numpy
from astropy.io import ascii
import units
import sqlite3
#from numba import autojit

import analyze
import constants
#===============================================================================

class Sink(object):
    def __init__(self,**properties):
        super(Sink,self).__init__()
        self.mass = properties.pop('m', None)
        self.x = properties.pop('x', None)
        self.y = properties.pop('y', None)
        self.z = properties.pop('z', None)
        self.pos = properties.pop('pos', None)
        self.radius = properties.pop('r', None)
        self.energy = properties.pop('e', None)
        self.pressure = properties.pop('p', None)
        self.npart_acc = properties.pop('n', None)
        self.pid = properties.pop('pid', None)
        self.index = properties.pop('index', None)

    def update_coordinates(self, x,y,z):
        self.x = x[self.index]
        self.y = y[self.index]
        self.z = z[self.index]

class SinkData(object):
    def __init__(self,path):
        super(SinkData,self).__init__()
        ### Read in the data
        try:
            sinkdata = ascii.read(path+'/sinkdat')
        except IOError:
            raise IOError("Specified sinkmasses file not found!")
        try:
            sinkmasses = ascii.read(path+'/sinkmasses')
        except IOError:
            raise IOError("Specified sinkmasses file not found!")

        self.time = sinkdata['col1']
        self.npart_acc = sinkdata['col2']
        self.radius = sinkdata['col3']
        self.part_internal_energy = sinkdata['col4']
        self.entropy = sinkdata['col5']
        self.part_id = sinkdata['col6']
        self.sink_id  = sinkdata['col7']
        self.pressure = sinkdata['col8']
        self.a = self.time # Scale Facor

        # Restrict to real sinks
        IDs = numpy.unique(sinkmasses['col2'])
        real = numpy.in1d(self.sink_id, IDs)
        for key in vars(self).keys():
            vars(self)[key] = vars(self)[key][real]

        h = 0.7 #Hubble Parameter
        h2 = h*h
        a3 = self.a**3
        ### Convert units
        self.time = self.time*units.Time_yr
        # npart_acc is a simple integer (no units)
        self.pressure = self.pressure*units.Pressure_cgs*h2/(a3**1.4)
        self.radius = self.radius*units.Length_AU*h

        good = numpy.where(self.radius > 10)[0]
        for key in vars(self).keys():
            vars(self)[key] = vars(self)[key][good]

class SinkHistory(SinkData):
    '''
    Select sink data for a single sink particle.

    possible options:
    nform: select the n(th) sink to form.
    ID: select sink by ID.
    '''
    def __init__(self, path, nform=None, id_=None):
        super(SinkHistory,self).__init__(path)
        unique = numpy.unique(self.sink_id)

        if((nform is None) and (id_ is None)):
            print "No sink specified: Selecting first sink to form..."
            nform = 1
        if nform:
            print "Key set: nform =", nform
            if id_: warnings.warn("nform key overrides id_")
            # Select n(th) sink to form
            new = []
            i = 0
            while len(new) < nform:
                if self.sink_id[i] not in new:
                    new.append(self.sink_id[i])
                i += 1
            id_ = new[-1]
        elif id_ is not None:
            print "Key set: id_ =", id_
        else:
            raise RuntimeError("Execution should not have reached this point!")
        print "Using sink ID", id_
        
        # Restrict to a single sink
        lines = numpy.where(self.sink_id == id_)
        for key in vars(self).keys():
            vars(self)[key] = vars(self)[key][lines]

        # Select final output for each timestep
        tsteps = numpy.unique(self.time)
        selection = []
        for t in tsteps:
            times = numpy.where(self.time == t)[0]
            selection.append(times[-1])
        for key in vars(self).keys():
                vars(self)[key] = vars(self)[key][selection]
        self.sink_id = id_
        self.nform = nform

        # Calculate sink mass at each timestep
        self.mass = numpy.zeros_like(self.time)
        for i in xrange(self.mass.size):
            self.mass[i] = 0.015*self.npart_acc[:i+1].sum()

        # Finally, record total number of sinks found.
        self.all_ids = unique

#===============================================================================
class AccretionDisk(object):
    def __init__(self, sim, sink, **kwargs):
        super(AccretionDisk, self).__init__()
        self.sim = sim
        self.sink = sink
        default = sim.plotpath +'/'+ sim.name
        if not os.path.exists(default):
            os.makedirs(default)
        dbfile = kwargs.pop('dbfile', default+'/disk{}.db'.format(sink.nform))
        self.db = sqlite3.connect(dbfile)
        self.c = self.db.cursor()

    def load(self, snap, density_limit=1e8, *dprops):
        fields = ''
        if dprops:
            for dprop in dprops[:-1]:
                fields += dprop + ', '
            fields += dprops[-1]
        else:
            fields = '*'
        table = 'snapshot{:0>4}'.format(snap)
        if density_limit:
            command = ("SELECT " + fields + " FROM " + table
                       + " WHERE density_limit = " + str(density_limit))
        else:
            command = "SELECT " + fields + " FROM " + table
        print '"'+command+'"'
        try:
            self.c.execute(command)
        except sqlite3.OperationalError:
            print "Warning: Error loading requested accretion disk data!"
            print "Recalculating..."
            self.populate(snap, density_limit, verbose=False)
            self.c.execute(command)

        self.data = numpy.asarray(self.c.fetchall())
        if self.data.size < 1:
            print "Warning: Requested accretion disk data does not exist!"
            print "Calculating..."
            self.populate(snap, density_limit, verbose=False)
            self.c.execute(command)
            self.data = numpy.asarray(self.c.fetchall())

    def populate(self, snap, density_limit, **kwargs):
        self.sim.units.set_length('cm')
        snapshot = self.sim.load_snapshot(snap, track_sinks=True)
        kwargs['dens_lim'] = density_limit
        diskprops = disk_properties(snapshot, self.sink.sink_id, **kwargs)
        snapshot.gas.cleanup()
        snapshot.close()
        print "Saving table containing", len(diskprops), "entries to database."
        table = 'snapshot{:0>4}'.format(snap)
        create = ("CREATE TABLE " + table +
                  "(density_limit real, "\
                  "redshift real, "\
                  "radius real, "\
                  "density real, "\
                  "total_mass real, "\
                  "shell_mass real, "\
                  "tff real, "\
                  "Tshell real, "\
                  "Tavg real, "\
                  "cs real, "\
                  "Lj real, "\
                  "Mj real, "\
                  "npart integer)")
        insert = ("INSERT INTO " + table +
                  "(density_limit, "\
                  "redshift, "\
                      "radius, "\
                      "density, "\
                      "total_mass, "\
                      "shell_mass, "\
                      "tff, "\
                      "Tshell, "\
                      "Tavg, "\
                      "cs, "\
                      "Lj, "\
                      "Mj, "\
                      "npart) "\
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)")
        try:
            self.c.executemany(insert, diskprops)
        except sqlite3.OperationalError:
            try:
                self.c.execute(create)
            except sqlite3.OperationalError:
                self.c.execute("DROP TABLE " + table)
                self.c.execute(create)

        self.c.executemany(insert, diskprops)
        self.db.commit()

#===============================================================================
def disk_properties(snapshot, sink_id, **kwargs):
    r_start = kwargs.pop('r_start', 1.49597871e13)
    r_step = kwargs.pop('r_step', 1.49597871e14)
    r_multiplier = kwargs.pop('multiplier', 1.2)
    verbose = kwargs.pop('verbose', True)
    n_min = kwargs.pop('n_min', 32)
    dens_lim = kwargs.pop('dens_lim', 1e8)
    redshift = snapshot.header.Redshift

    length_unit = 'cm'
    mass_unit = 'g'

    i = 0
    print 'Locating sink...'
    while snapshot.sinks[i].pid != sink_id:
        i += 1
    print 'Done'
    sink = snapshot.sinks[i]
    xyz = (sink.pos[0], sink.pos[1],sink.pos[2])
    pos = snapshot.gas.get_coords(length_unit, system='spherical', center=xyz)
    dens = snapshot.gas.get_number_density('cgs')
    mass = snapshot.gas.get_masses(mass_unit)
    temp = snapshot.gas.get_temperature()

    if dens_lim:
        dens,pos,mass,temp = analyze.density_cut(dens_lim, dens, pos, mass, temp)
    r = pos[:,0]

    print 'Data loaded.  Analyzing...'
    GRAVITY = 6.6726e-8 # dyne * cm**2 / g**2
    disk_properties = []
    n = 0
    old_n = 0
    old_r = 0
    density = 0
    energy = 0
    rmax = r_start
    while n < r.size:
        inR = numpy.where(r <= rmax)[0]
        n = inR.size
        if n > old_n + n_min:
            inShell = numpy.where((r > old_r) & (r <= rmax))[0]
            rau = rmax/1.49597871e13
            Mtot = mass[inR].sum()
            Mshell = mass[inShell].sum()
            Msun = Mtot/1.989e33
            density = dens[inShell].mean()
            if numpy.isnan(density):
                density = dens.max()
            mdensity = density * constants.m_H / constants.X_h
            tff = numpy.sqrt(3 * numpy.pi / 32 / constants.GRAVITY / mdensity)
            T = analyze.reject_outliers(temp[inShell]).mean()
            tavg = analyze.reject_outliers(temp[inR]).mean()
            cs = numpy.sqrt(constants.k_B * T / constants.m_H)
            Lj = cs*tff
            Mj = density * (4*numpy.pi/3) * Lj**3 / 1.989e33
            if verbose:
                print 'R = %.2e AU' %rau,
                print 'Mass enclosed: %.2e' %Msun,
                print 'density: %.3e' %density,
                print 'npart: {}'.format(n)
            disk_properties.append((dens_lim,redshift,rau,density,Msun,Mshell,
                                    tff,T,tavg,cs,Lj,Mj,n))

            old_n = n
            old_r = rmax
        rmax *= r_multiplier
    print 'snapshot', snapshot.number, 'analyzed.'
    return disk_properties
