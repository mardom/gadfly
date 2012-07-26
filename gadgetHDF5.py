# gadgetHDF5.py
# Jacob Hummel
"""
This module contains classes for reading Gadget2 HDF5 snapshot data.
"""

import h5py

class Snapshot:
    """
    Base Class for Gadget2 HDF5 snapshot files
    """
    def __init__(self, filename):
        self.file_id = h5py.File(filename, 'r')
        self.header = Header(self.file_id)
        self.gas = PartTypeX(self.file_id, 0)
        self.dm = PartTypeX(self.file_id, 1)
        
    def keys(self):
        for key in self.file_id.keys():
            print key
        
    def close(self):
        self.file_id.close()

class HDF5Group:
    """
    Base Class for HDF5 groups
    """
    def keys(self):
        for key in vars(self):
            print key

class Header(HDF5Group):
    """
    Class for header information from Gadget2 HDF5 snapshots.
    """
    def __init__(self, file_id):
        group = file_id['Header']
        for key in group.attrs.items():
            vars(self)[key[0]] = key[1]
            
class PartTypeX(HDF5Group):
    """
    Class for dark matter particle info.
    """
    def __init__(self, file_id, ptype):
        group = file_id['PartType'+str(ptype)]
        for item in group.items():
            key = item[0].replace(' ', '_')
            vars(self)[key] = item[1]

        

