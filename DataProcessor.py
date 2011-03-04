import tables as tab
import numpy as np
import os
import re

def fill_table(datafile):
    '''Adds all the data to the table'''

    # load the files from the data/h5 directory
    pathtoh5 = os.path.join('..', 'BicycleDAQ', 'data', 'h5')
    files = sorted(os.listdir(pathtoh5))
    # open a new hdf5 file for appending
    data = tab.openFile(datafile, mode='a')
    # get the table
    rawtable = data.root.rawdata.rawdatatable
    # get the row
    row = rawtable.row
    # fill the rows with data
    for run in files:
        print run
        rundata = get_run_data(os.path.join(pathtoh5, run))
        for par, val in rundata['par'].items():
            row[par] = val
        #for i, col in enumerate(rundata['NICols']):
            #print row[col].shape, rundata['NIData'][i].shape
            #row[col] = rundata['NIData'][i]
        #for i, col in enumerate(rundata['VNavCols']):
            #row[col] = rundata['VNavData'][i]
        row.append()
    rawtable.flush()
    data.close()

def create_database():
    '''Creates an HDF5 file for data collected from the instrumented bicycle'''

    # load the latest file in the data/h5 directory
    pathtoh5 = os.path.join('..', 'BicycleDAQ', 'data', 'h5')
    files = sorted(os.listdir(pathtoh5))
    rundata = get_run_data(os.path.join(pathtoh5, files[-1]))
    # generate the table description class
    RawRun = create_raw_run_class(rundata)
    # open a new hdf5 file for writing
    data = tab.openFile('InstrumentedBicycleData.h5', mode='w',
                               title='Instrumented Bicycle Data')
    # create a group for the raw data
    rgroup = data.createGroup('/', 'rawdata', 'Raw Data')
    # add the data table to this group
    rtable = data.createTable(rgroup, 'rawdatatable', RawRun, 'Primary Data Table')
    rtable.flush()
    data.close()

def create_raw_run_class(rundata):
    '''Generates a class that is used for the table description for raw data
    for each run.

    Parameters
    ----------
    rundata : dict
        Contains the python dictionary of a particular run.

    Returns
    -------
    Run : class
        Table description class for pytables with columns defined.

    '''
    # set up the table description
    class RawRun(tab.IsDescription):
        # add all of the column headings from par, NICols and VNavCols
        for i, col in enumerate(rundata['NICols']):
            exec(col + " = tab.Float32Col(shape=(6000, ), pos=i)")
        for k, col in enumerate(rundata['VNavCols']):
            exec(col + " = tab.Float32Col(shape=(6000, ), pos=i+1+k)")
        for i, (key, val) in enumerate(rundata['par'].items()):
            pos = k+1+i
            if isinstance(val, type(1)):
                exec(key + " = tab.Int64Col(pos=pos)")
            elif isinstance(val, type('')):
                exec(key + " = tab.StringCol(itemsize=50, pos=pos)")
            elif isinstance(val, type(1.)):
                exec(key + " = tab.Float64Col(pos=pos)")
            elif isinstance(val, type(np.ones(1))):
                exec(key + " = tab.Float64Col(shape=(" + str(len(val)) + ", ), pos=pos)")

        # get rid of these intermediate variables
        del(i, k, col, key, pos, val)

    return RawRun

def parse_vnav_string(vnstr, remove=0):
    '''Gets the good info from a VNav string

    Parameters
    ----------
    vnstr : string
        A string from the VectorNav serial output.
    remove : int
        Specifies how many values to remove from the beginning of the output
        list. Useful for removing VNWRG, etc.

    Returns
    -------
    vnlist : list
        A list of each element in the VectorNav string.
        ['VNWRG', '26', ..., ..., ...]

    '''
    # get rid of the $ and the *checksum
    vnstr = re.sub('\$(.*)\*.*', r'\1', vnstr)
    # make it a list
    vnlist = vnstr.split(',')
    # return the last values with regards to remove
    return vnlist[remove:]

def get_run_data(pathtofile):
    '''Returns data from the run h5 files using pytables and formats it better
    for python.

    Parameters
    ----------
    pathtofile : string
        The path to the h5 file that contains run data.

    Returns
    -------
    rundata : dictionary
        A dictionary that looks similar to how the data was stored in Matlab.

    '''

    # open the file
    runfile = tab.openFile(pathtofile)

    # intialize a dictionary for storage
    rundata = {}

    # first let's get the NIData and VNavData
    rundata['NIData'] = runfile.root.NIData.read()
    rundata['VNavData'] = runfile.root.VNavData.read()

    # now create two lists that give the column headings for the two data sets
    rundata['VNavCols'] = [str(x) for x in runfile.root.VNavCols.read()]
    # hack because the Mags may come with hex shit at the end like \x03
    for i, col in enumerate(rundata['VNavCols'][:3]):
        rundata['VNavCols'][i] = col[:5]
    rundata['VNavCols'] = [x.replace(' ', '') for x in rundata['VNavCols']]
    rundata['NICols'] = []
    # make a list of NI columns from the InputPair structure from matlab
    for col in runfile.root.InputPairs:
        rundata['NICols'].append((str(col.name), int(col.read()[0])))

    rundata['NICols'].sort(key=lambda x: x[1])

    rundata['NICols'] = [x[0] for x in rundata['NICols']]

    # put the parameters into a dictionary
    rundata['par'] = {}
    for col in runfile.root.par:
        # convert them to regular python types
        try:
            if col.name == 'Speed':
                rundata['par'][col.name] = float(col.read()[0])
            else:
                rundata['par'][col.name] = int(col.read()[0])
        except:
            pstr = str(col.read()[0])
            rundata['par'][col.name] = pstr
            if pstr[0] == '$':
                parsed = parse_vnav_string(pstr, remove=2)
                if len(parsed) == 1:
                    try:
                        parsed = int(parsed[0])
                    except:
                        parsed = parsed[0]
                else:
                    parsed = np.array([float(x) for x in parsed])
                rundata['par'][col.name] = parsed

    # get the VNavDataText
    rundata['VNavDataText'] = [str(x) for x in runfile.root.VNavDataText.read()]

    # close the file
    runfile.close()

    return rundata
