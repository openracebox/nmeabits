
import sys
import socket

from datetime import datetime, date
from time import sleep, time
from operator import xor
from pprint import pprint

sys.path.append("..")
from nmeabits import ParseError, FormatError
from functools import reduce


class nmeaParser(object):
    """
    An NMEA message reader and parser.

    >>> s = nmeaParser()
    """
    def __init__(self):
        self.stats = {"ts_start": time(),
                      "n_msg": 0,  # Valid messages seen.
                      "n_nopre": 0,
                      "n_noproc": 0,
                      "err_checksum": 0,
                      "err_format": 0,
                      "err_linefeed": 0,
                      "missing_checksum": 0,
                      "n_bytes": 0,
        }

        # processors should prefix their keys with their name,
        # if using this store.
        self.state = {}

    def process(self, msg):
        "Parse and process a NMEA message"
        # Filter numerous instances of this broken checksum format.
        # $VWVHW,,T,,M,0.00,N,0.00*K1F
        if msg.endswith("*K1F\r\n"):
            return

        sep = msg.find(",")
        if sep < 0:
            self.stats["err_format"] += 1
            return

        if msg[-2:] != "\r\n":
            self.stats["err_linefeed"] += 1

        if msg[-5] == '*':
            payload = msg[1:len(msg) - 5]

            checksum = "%02x" % reduce(xor, (ord(s) for s in payload))
            checksum = checksum.upper()
            if checksum != msg[-4:-2]:
                self.stats["err_checksum"] += 1
                s = "Invalid checksum: %s (computed: %s)"
                #print s % (msg[:-2], checksum)
                return
        else:
            self.stats["missing_checksum"] += 1

        msgtype = msg[1:sep].upper()

        # Filter checksum and line feed.
        msg = msg[:-5]

        self.stats["n_msg"] += 1
        self.stats["n_bytes"] += len(msg)

        statkey = "n_%s" % msgtype
        try:
            self.stats[statkey] += 1
        except KeyError:
            self.stats[statkey] = 1

        prepared = {}
        msgparts = msg.split(",")

        func = getattr(self, "prepare_%s" % msgtype, None)
        if func is None:
            self.stats["n_nopre"] += 1
            # Don't return, allow the processor to do all the
            # work if needed.
        else:
            try:
                prepared = func(msgparts)
            except AssertionError as e:
                raise
            except Exception as e:
                # XXX: Improve logging.
                print("ERR: prepare_%s(): " % msgtype + str(e))
                print(msgparts)
                raise

        assert type(prepared) == dict

        # Prepare step can rewrite the message. (within reason)
        if "msg" in prepared:
            assert prepared["msg"].startswith("$%s" % msgtype)
            assert not prepared["msg"].endswith("\r\n")
            msgparts = prepared["msg"].split(",")
            del prepared["msg"]

        prepared["source"] = msgtype

        # Run the user defined processing function.
        func = getattr(self, "process_%s" % msgtype, None)
        if func is None:
            self.stats["n_noproc"] += 1
            if 0:
                pprint(msgtype)
        else:
            try:
                func(msgparts, prep=prepared, state=self.state)
            except AssertionError as e:
                raise
            except Exception as e:
                print("process_%s(): " % msgtype + str(e))

        self.process_any(msgparts, prep=prepared, state=self.state)

    def process_any(self, msgparts, prep={}, state={}):
        "Catch-all"
        return

    def print_stats(self, outputfd=sys.stdout):
        """
        >>> from os import devnull
        >>> nmeaParser().print_stats(outputfd=open(devnull, "w"))
        """
        uptime = time() - self.stats["ts_start"]
        #print(datetime.now(), file=outputfd)
        fmt = "%15s: %s\t(%.3f %s/s)"
        for key, value in sorted(self.stats.items()):
            if key in ["ts_start"]:
                continue
            unit = "msg"
            if key in ["n_bytes"]:
                unit = "bytes"
            print(fmt % (key, value, value / uptime, unit), file=outputfd)
        print("", file=outputfd)

    # Preprocessors, sorted alphabetically.
    def prepare_FBMWV(self, msgparts):
        """
        Wind direction and strength.

        This is a Freeboard proprietary NMEA message.

        Format documentation:

            https://github.com/rob42/freeboardPLC/blob/master/NmeaSerial.cpp#L53

        >>> "msg" in nmeaParser().prepare_FBMWV("$FBMWV,231.0,R,13.99,N,A*3B".split(','))
        True
        >>> len(nmeaParser().prepare_FBMWV("$FBMWV,231.0,R,13.99,N,A*3B".split(',')))
        3
        """
        assert type(msgparts) == list
        res = {}

        # Initial message parsing
        try:
            angle = float(msgparts[1])
            res["AWA"] = float(msgparts[1])
            res["AWS"] = float(msgparts[3])
        except ValueError as e:
            raise ParseError(e)

        if msgparts[2] != "R":
            raise NotImplemented("Only relative wind is supported")

        # Check for sanity.
        if not (res["AWA"] >= 0.0 and res["AWA"] <= 360.0):
            raise ParseError("Wind angle out of bounds")

        if (res["AWS"] < 0.0):
            raise ParseError("Negative wind speed")

        # Enough (?) not to be reached, but sufficiently below
        # 360 to catch format ordering (angle as strength) mixups.
        if (res["AWS"] > 200):
            raise ParseError("Insane wind speed. Go to port.")

        # Our wind gauge is mounted backwards. Adjust the angle.
        angle = (angle + 180) % 360
        msgparts[1] = "%.0f" % angle
        res["msg"] = ','.join(msgparts)

        return res

    def prepare_GPGGA(self, msgparts):
        """
        Global Positioning System Fix Data.

        http://aprs.gids.nl/nmea/#gga

        $GPGGA,173151.000,5953.6205,N,01035.1888,E,1,08,01.0,-0000.9,M,0040.8,M,000.0,0000*56
        """
        return {}

    def prepare_GPGLL(self, msgparts):
        """
        Geographic Latitude and Longitude.

        $GPGLL,5926.5539,N,01033.8997,E,131958.000,A*3F

        No use in doing anything here, we have this data from
        GPRMC already.
        """
        return {}

    def prepare_GPGSA(self, msgparts):
        """
        GPS DOP and active satellites. The nature of the GPS fix.

        >>> nmeaParser().prepare_GPGSA("$GPGSA,A,3,06,22,21,15,03,08,27,07,16,18,19,,01.7,00.9,01.4*06".split(","))
        {'fix': 3, 'VDOP': None, 'PDOP': 1.7, 'HDOP': 0.9}
        >>> nmeaParser().prepare_GPGSA("$GPGSA,A,1,,,,,,,,,,,,,,,,*32".split(","))
        {'fix': 1, 'VDOP': None, 'PDOP': None, 'HDOP': None}

        """
        assert type(msgparts) == list

        res = {}
        res["fix"] = int(msgparts[2])
        for index, key in [
                            (-3, "PDOP"),
                            (-2, "HDOP"),
                            (-1, "VDOP")]:
            res[key] = None
            try:
                res[key] = float(msgparts[index])
            except ValueError:
                pass

        # Disable this verification for now. Values of up to
        # 9.0 seen in data dumps, which seems odd.
        #for key, value in res.items():
        #    if "DOP" not in key:
        #        continue
        #    if value > 3.0:
        #        raise ParseError("%s is invalid (%.2f)" % \
        #                         (key, value))
        return res

    def prepare_GPGSV(self, msgparts):
        """
        Satellites in view.

        Multiline.

        $GPGSV,3,1,11,25,84,195,29,12,47,100,32,29,42,207,35,31,40,299,24*7A
        $GPGSV,3,2,11,02,38,086,30,04,25,046,31,14,24,242,24,24,07,152,32*78
        $GPGSV,3,3,11,20,04,341,29,32,01,315,19,10,01,066,31*4F

        Not especially useful.
        """
        return {}

    def prepare_GPRMC(self, msgparts):
        """
        >>> nmeaParser().prepare_GPRMC("$GPRMC,133725,V,3851.3970,N,09500.5709,W,0.0000,0.000,300416,,*2C".split(","))
        {'SOG': 0.0, 'lon': '09500.5709W', 'COG': 0.0, 'lat': '3851.3970N', 'ts_GPS': datetime.datetime(1900, 1, 1, 13, 37, 25), 'date_GPS': datetime.datetime(2016, 4, 30, 0, 0)}

        """
        assert type(msgparts) == list
        res = {}

        try:
            # is this WGS84?
            res["lat"] = msgparts[3] + msgparts[4]
            res["lon"] = msgparts[5] + msgparts[6]

            # Speed Over Ground
            res["SOG"] = float(msgparts[7])

            # Course over Ground
            res["COG"] = float(msgparts[8])

            res["date_GPS"] = datetime.strptime(msgparts[9], "%d%m%y")
            res["ts_GPS"] = datetime.strptime(msgparts[1], "%H%M%S")

            #res["dt_GPS"] = datetime.strptime(
            #                    msgparts[9] + msgparts[1] + "UTC",
            #                    "%d%m%y%H%M%S.%f%Z")
        except ValueError as e:
            raise ParseError(e)

#        if msgparts[2] != "A":
#            raise NotImplemented()

        if res["date_GPS"].date() < date(year=2000, month=1, day=1):
            raise ParseError("GPS timestamp is ancient")

        if (res["COG"] < 0.0 or res["COG"] > 360.0):
            raise ParseError("Invalid course")

        if (res["SOG"] >= 100.0):
            raise ParseError("Insane speed")

        # TODO: use variation.
        return res

    def process_GPRMC(self, msgparts, prep={}, state={}):
        return
        pprint(msgparts)
        pprint(prep)
        pprint(state)
        return


if __name__ == "__main__":
    import doctest
    nt = nmeaParser()
    doctest.testmod(extraglobs={'nt': nt})
    #nt.print_stats()
