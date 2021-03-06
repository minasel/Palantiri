from pyrocko.client import fdsn, catalog
import os
from pyrocko import util, io, trace, model, gf
import sys
sys.path.append('../tools/')
sys.path.append('../Common/')
import config
import Globals                     # Own global data
import Basic                       # Own module with basic functions
import Logfile                     # Implements logfile
import ConfigFile                  # Semantic of config file entries
import Debug
import DataTypes                   # Common data types
import KeyFile
import DataDir
from optparse import OptionParser
from   ConfigParser import SafeConfigParser
from pyrocko import util, io, trace, cake
from   config import Event, Trigger
from    ConfigFile import ConfigObj, FilterCfg, OriginCfg
global options,args
from pyrocko.io import stationxml



def main(args):

    parser = OptionParser(usage="\npython %prog -t 2009-12-31T12:23:34 -d 5 -m SDS -k key -s all/acq")

    parser.add_option("-t","--time",      type="string", dest="time",      help="time")
    parser.add_option("-d","--duration",  type="string", dest="duration",  help="duration in min")
    parser.add_option("-m","--sdsfolder", type="string", dest="sdsfolder", help="sdsfolder")
    parser.add_option("-s","--station",   type="string", dest="stationversion", help="stationversion")
    parser.add_option("-f","--evpath",    type="string", dest="eventpath", help="eventpath")
    parser.add_option("-x","--dummy",     type="string", dest="station",   help="dummy")    #hs: client flag
    parser.add_option("-n","--dummy2",    type="string", dest="network",   help="dummy2")   #hs: single network

    return parser.parse_args(args)

def globalConf():

    cDict  = {}
    parser = SafeConfigParser()
    parser.read(os.path.join('..', 'global.conf'))

    for section_name in parser.sections():
        for name, value in parser.items(section_name): cDict[name] = value

    return cDict

options,args = main(sys.argv)
Basic.checkExistsDir(options.eventpath, isAbort=True)
Globals.setEventDir(options.eventpath)
C = config.Config(options.eventpath)
Origin = C.parseConfig('origin')
Conf = globalConf()
Config = C.parseConfig('config')

filter = FilterCfg(Config)

cfg = ConfigObj(dict=Config)
minDist, maxDist = cfg.FloatRange('mindist', 'maxdist')

ev = Event(Origin['lat'],Origin['lon'],Origin['depth'],Origin['time'] )
event = model.Event(lat=float(ev.lat), lon=float(ev.lon), depth=float(ev.depth)*1000., time=util.str_to_time(ev.time))
newFreq = float(filter.newFrequency())
options.time = Origin ['time']
options.duration = int(Conf['duration'])
sdspath = os.path.join(options.eventpath,'data')
model.dump_events([event], sdspath+'event.pf')

tmin = util.str_to_time(ev.time)-600.
tmax = util.str_to_time(ev.time)+1800.

def get_stations(site, lat, lon, rmin, rmax, tmin, tmax, channel_pattern='BH*'):
    extra = {}
    if site == 'iris':
        extra.update(matchtimeseries=True)

    sx = fdsn.station(
            site=site, latitude=lat, longitude=lon,
            minradius=rmin, maxradius=rmax,
            startbefore=tmin, endafter=tmax, channel=channel_pattern,
            format='text', level='channel', includerestricted=False)

    return sx.get_pyrocko_stations()

site = 'iris'
stations_iris = get_stations(site, event.lat,event.lon,minDist, maxDist,tmin,tmax, 'BHZ')

nstations_iris = [s for s in stations_iris]

selection_iris = fdsn.make_data_selection(nstations_iris, tmin, tmax)
request_waveform_iris = fdsn.dataselect(site=site, selection=selection_iris)

# write the incoming data stream to 'traces.mseed'
with open(os.path.join(sdspath,'traces_iris.mseed'), 'wb') as file:
    file.write(request_waveform_iris.read())
print('traces written')
# request meta data
traces_iris = io.load(os.path.join(sdspath,'traces_iris.mseed'))

stations_real_iris = []
gaps= []
for tr in traces_iris:
    for st in stations_iris:
        if tr.station == st.station and tr.location == st.location:
                stations_real_iris.append(st)
                gaps.append(st.station)
remove =[x for x in gaps if gaps.count(x) > 1]
for re in remove:
    for st in stations_real_iris:
        if st.station == re:
            stations_real_iris.remove(st)
model.dump_stations(stations_real_iris, os.path.join(sdspath,'stations_iris.txt'))

request_response = fdsn.station(
    site=site, selection=selection_iris, level='response')
# save the response in YAML and StationXML format
request_response.dump(filename=os.path.join(sdspath,'responses_iris.yml'))
request_response.dump_xml(filename=os.path.join(sdspath,'responses_iris.xml'))
sx = stationxml.load_xml(filename=os.path.join(sdspath,'responses_iris.xml'))
pyrocko_stations = sx.get_pyrocko_stations()
#model.dump_stations(stations_real, os.path.join(sdspath,'stations2.txt'))

# Loop through retrieved waveforms and request meta information
# for each trace
event_origin = gf.Source(
lat=event.lat,
lon=event.lon)

traces_iris = io.load(os.path.join(sdspath,'traces_iris.mseed'))


displacement_iris = []
stations_disp_iris = []
for tr in traces_iris:
    for station in stations_real_iris:
        if tr.station == station.station and tr.location == station.location:
            try:
                polezero_response = request_response.get_pyrocko_response(
                nslc=tr.nslc_id,
                timespan=(tr.tmin, tr.tmax),
                fake_input_units='M')
                # *fake_input_units*: required for consistent responses throughout entire
                # data set

                # deconvolve transfer function
                restituted = tr.transfer(
                tfade=2.,
                freqlimits=(0.01, 0.1, 1., 2.),
                transfer_function=polezero_response,
                invert=True)

                displacement_iris.append(restituted)
                stations_disp_iris.append(station)
            except:
                pass


io.save(displacement_iris, os.path.join(sdspath,'traces_restituted_iris.mseed'))
model.dump_stations(stations_disp_iris, os.path.join(sdspath,'stations_disp_iris.txt'))

site = 'geofon'
minDist, maxDist = cfg.FloatRange('mindist', 'maxdist')
diffDist =(maxDist - minDist)/6.
displacement_geofon = []
stations_disp_geofon = []
stations_real_geofon = []
gaps= []
try:
    for l in range(0,6):
        maxDist = minDist+diffDist
        stations_geofon = get_stations(site, event.lat,event.lon,minDist, maxDist,tmin,tmax, 'BHZ')

        nstations_geofon = [s for s in stations_geofon]

        selection_geofon = fdsn.make_data_selection(nstations_geofon, tmin, tmax)
        request_waveform_geofon = fdsn.dataselect(site=site, selection=selection_geofon)

        # write the incoming data stream to 'traces.mseed'
        with open(os.path.join(sdspath,'traces_geofon_part%s.mseed' %l), 'wb') as file:
            file.write(request_waveform_geofon.read())
        print('traces written')
        # request meta data
        traces_geofon = io.load(os.path.join(sdspath,'traces_geofon_part%s.mseed' %l))

        for tr in traces_geofon:
            for st in stations_geofon:
                if tr.station == st.station and tr.location == st.location:
                        stations_real_geofon.append(st)
                        gaps.append(st.station)
        remove =[x for x in gaps if gaps.count(x) > 1]
        for re in remove:
            for st in stations_real_geofon:
                if st.station == re:
                    stations_real_geofon.remove(st)
        model.dump_stations(stations_real_geofon, os.path.join(sdspath,'stations_geofon_part%s.txt' %l))
        request_response = fdsn.station(
            site=site, selection=selection_geofon, level='response')
        # save the response in YAML and StationXML format
        request_response.dump(filename=os.path.join(sdspath,'responses_geofon_part%s.yml'%l))
        request_response.dump_xml(filename=os.path.join(sdspath,'responses_geofon_part%s.xml'%l))
        sx = stationxml.load_xml(filename=os.path.join(sdspath,'responses_geofon_part%s.xml'%l))
        pyrocko_stations = sx.get_pyrocko_stations()
        # Loop through retrieved waveforms and request meta information
        # for each trace
        event_origin = gf.Source(
        lat=event.lat,
        lon=event.lon)

        traces_geofon = io.load(os.path.join(sdspath,'traces_geofon_part%s.mseed' %l))

        for tr in traces_geofon:
            for station in stations_real_geofon:
                if tr.station == station.station and tr.location == station.location:
                    try:
                        polezero_response = request_response.get_pyrocko_response(
                        nslc=tr.nslc_id,
                        timespan=(tr.tmin, tr.tmax),
                        fake_input_units='M')
                        # *fake_input_units*: required for consistent responses throughout entire
                        # data set

                        # deconvolve transfer function
                        restituted = tr.transfer(
                        tfade=2.,
                        freqlimits=(0.01, 0.1, 1., 2.),
                        transfer_function=polezero_response,
                        invert=True)

                        displacement_geofon.append(restituted)
                        stations_disp_geofon.append(station)
                    except:
                        pass
        minDist = minDist+diffDist
except:
        pass

io.save(displacement_geofon, os.path.join(sdspath,'traces_restituted_geofon.mseed'))
model.dump_stations(stations_disp_geofon, os.path.join(sdspath,'stations_disp_geofon.txt'))

stations_all  = stations_real_iris+stations_real_geofon
for stg in stations_real_geofon:
    for sti in stations_real_iris:
        if sti.station == stg.station and sti.location == stg.location:
            try:
                stations_all.remove(sti)
            except:
                pass
        else:
            pass
traces_all = traces_iris+traces_geofon
io.save(traces_all, os.path.join(sdspath,'traces.mseed'))
model.dump_stations(stations_all, os.path.join(sdspath,'stations.txt'))

stations_all_disp = stations_disp_iris+stations_disp_geofon
for stg in stations_disp_geofon:
    for sti in stations_disp_iris:
        if sti.station == stg.station and sti.location == stg.location:
            try:
                stations_all_disp.remove(sti)
            except:
                pass
        else:
            pass
traces_all_disp = displacement_iris+displacement_geofon
io.save(traces_all_disp, os.path.join(sdspath,'traces_restituted.mseed'))
model.dump_stations(stations_all_disp, os.path.join(sdspath,'stations_disp.txt'))
