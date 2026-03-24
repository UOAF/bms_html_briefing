import datetime as dt
from math import sin, asin, cos, tan, atan2, radians, degrees
## date is in YYYY MM DD
date0 = dt.date(2000, 1, 6)

## Based on J. Meeus, "Astronomical observations", Chapters 45, 47

#  ----------------------------
# Helper functions
# ----------------------------

# Convert date to Meeus T value from JDE; we don't distinguish between JD and JDE
def date_to_JD(d):
    Y = d.year
    M = d.month
    D = d.day

    if (M == 1 or M == 2):
        Y = Y - 1
        M = M + 12
    A = int(Y/100)
    B = 2- A + int(A/4)
    JD = int(365.25*(Y+4716)) + int(30.6001*(M+1)) + D + B - 1524.5
    return JD + (d.hour/24 + d.minute/(24*60) + d.second/(24*3600))

def date_to_T(d):
    return (date_to_JD(d)-2451545)/36525

## sidereal time at Greenwich at 0h Universal Time at a given date; note that T should correspond to 0h UT at given date (should end at 0.5)

def sidereal_time_Greenwich_0h(T): #theta_0 in Meeus
    return (100.46061837
            + 36000.770053608*T
            + 0.000387933*(T**2)
            - (T**3)/38710000) % 360

def sidereal_time_Greenwich(d): #this works for any time of day
    T = date_to_T(d)
    jd = date_to_JD(d)
    return (280.46061837
            + 360.98564736629*(jd - 2451545)
            + 0.000387933*(T**2)
            - (T**3)/38710000) % 360

# obliquity (no nutation)
def eps(T):
    return (23
            + 26/60
            + 21.448/3600
            - (46.8150/3600)*T
            - (0.00059/3600)*(T**2)
            + (0.001813/3600)*(T**3))

## Formula (47.1) without the offset by Julian Ephemeris Days to date0
def delta_JDE(k):
    Tp = k/1236.85
    return (29.530588853*k
            + 0.0001337*(Tp**2)
            - 0.000000150*(Tp**3)
            + 0.00000000073*(Tp**4))

## In fact, for our purposes just the linear term is enough
def delta_JDE_crude(k):
    return (29.530588853*k)

def angle_to_HA_crude(a):
    ac = a % 360
    return dt.time(hour = int(ac/360*24), minute = int((ac/360*24 - int(ac/360*24))*60))

def HA_to_angle(t):
    t_dec = t.hour + t.minute/60 + t.second/3600
    return t_dec*15 if t_dec*15 <= 180 else t_dec*15-360
    

# ----------------------------
# Output functions
# ----------------------------

## Meeus gives only 4 phases and says other values would be meaningless; we will not use the function above and instead use the linear interpolation in moonphase_crude. The function below is left just in case.

def moonphase(date):
    delta_days = (date - date0).days
    k = (delta_days)/365*12.3685
    # compute a full moon nearby
    k_int = int((date - date0).days/365*12.3685)
    # Compute several nearby phases and see where ours fits; stupid, but it seems to work for the last ~75 years.
    phases = [delta_JDE(k_int + 0.25*i) for i in range(-4, 5)]
    for i in range(-4, 4):
        if phases[i+4] <= delta_days <= phases[i+4+1]:
            if (i+4) % 4 == 0:
                if (delta_days - phases[i+4]) < 2:
                    return "New Moon 🌑"
                else:
                    return "First Quarter 🌒"
            if (i+4) % 4 == 1:
                if (phases[i+4+1] - delta_days < 2):
                    return "Full Moon 🌕"
                else:
                    return "Second Quarter 🌔"
            if (i+4)% 4 == 2:
                if (delta_days - phases[i+4]) < 2:
                    return "Full Moon 🌕"
                else:
                    return "Third  Quarter 🌖"
            if (i+4) % 4 == 3:
                if (phases[i+4+1] - delta_days < 2):
                    return "New Moon 🌑"
                else:
                    return "Last Quarter 🌘"
    return "undefined"

def moonphase_crude(date):
    delta_days = (date - date0).days
    phase = int(delta_days*100/29.530588853) % 100
    if (phase < 5) or (phase > 95):
        return "New Moon 🌑"
    if (phase >= 5) and (phase <=20):
        return "Waxing Crescent"
    if (phase > 20) and (phase <=30):
        return "First Quarter"
    if (phase > 30) and (phase <=45):
        return "Waxing Gibbous"
    if (phase > 45) and (phase <= 55):
        return "Full Moon"
    if (phase > 55) and (phase <= 70):
        return "Waning Gibbous"
    if (phase > 70) and (phase <=80):
        return "Third Quarter"
    if (phase > 80) and (phase <=95):
        return "Waning Crescent"
    return "undefined"

# Formulas from Chapter 45. Returns geocentric longitude (\lambda) and latitude (\beta).
def moon_long_lat(date, accuracy = 60):
    T = date_to_T(date)
    Lp = radians((218.3164591
          + 481267.88134236*T
          - 0.0013268*(T**2)
          + (T**3)/538841
          - (T**4)/6519400) % 360)
    D = radians((297.8502042
         + 445267.1115168*T
         - 0.0016300*(T**2)
         + (T**3)/545868
         - (T**4)/113065000) % 360)
    M = radians((357.5291092
         + 35999.0502909*T
         - 0.0001536*(T**2)
         + (T**3)/24490000) % 360)
    Mp = radians((134.9634114
          + 477198.8676313*T
          + 0.0089970*(T**2)
          + (T**3)/69699
          - (T**4)/14712000) % 360)
    F = radians((93.2720993
         + 483202.0175273*T
         - 0.0034029*(T**2)
         - (T**3)/3526000
         + (T**4)/863310000) % 360)
    A1 = radians((119.75 + 131.849*T) % 360)
    A2 = radians((53.09 + 479264.290*T) % 360)
    A3 = radians((313.45 + 481266.484*T) % 360)

    E = 1 - 0.002516*T - 0.0000074*(T**2)

    l = [(E**(abs(c[1])))*c[4]*sin((c[0]*D + c[1]*M + c[2]*Mp + c[3]*F)) for c in SIGMA_LR_TERMS[0:accuracy]]
    b = [(E**(abs(c[1])))*c[4]*sin((c[0]*D + c[1]*M + c[2]*Mp + c[3]*F)) for c in SIGMA_B_TERMS[0:accuracy]]

    Sl_additive = (3958*sin(A1)
                   + 1962*sin(Lp - F)
                   + 318*sin(A2))
    Sb_additive = (-2235*sin(Lp)
                   +382*sin(A3)
                   +175*sin(A1-F)
                   +175*sin(A1+F)
                   +127*sin(Lp - Mp)
                   -115*sin(Lp+Mp))

    Sl = sum(l) + Sl_additive
    Sb = sum(b) + Sb_additive

    lambd = (degrees(Lp) + Sl/(10**6)) % 360
    beta = (Sb/(10**6)) % 360

    return(lambd, beta)

# Coordinate conversion to right ascension and declination
def moon_asc_decl(date, accuracy = 60):
    (lambd, beta) = [radians(x) for x in moon_long_lat(date, accuracy = accuracy)]
    T = date_to_T(date)
    reps = radians(eps(T))
    alpha = atan2((sin(lambd)*cos(reps)-tan(beta)*sin(reps)),(cos(lambd)))
    delta = asin(sin((beta))*cos((reps))+cos((beta))*sin((reps))*sin((lambd)))
    return (degrees(alpha), degrees(delta))

# longitude is positive West of Greenwich, latitude positive North
def moon_angle_above_horizon(date, latitude, longitude, accuracy = 60):
    rlatitude = radians(latitude)
    (alpha, delta) = moon_asc_decl(date, accuracy = accuracy)
    rdelta = radians(delta)
    H = sidereal_time_Greenwich(date) - longitude - alpha
    rH = radians(H)
    return degrees(asin(sin(rlatitude)*sin(rdelta) + cos(rlatitude)*cos(rdelta)*cos(rH)))

# time of day is ignored and output is in UT
def moon_rise_set_times(day, latitude, longitude, accuracy = 60):
    # compute angle every two minutes
    date = dt.datetime.combine(day, dt.time.min)
    tt = [date + n*dt.timedelta(minutes = 2) for n in range(24*30)]
    hh = [moon_angle_above_horizon(t, latitude = latitude, longitude = longitude, accuracy = accuracy) for t in tt]
    rise_ends = [i for i in range(len(tt)-1) if hh[i] <= 0 and hh[i+1] > 0]
    set_ends = [i for i in range(len(tt)-1) if hh[i] >= 0 and hh[i+1] < 0]
    rise = [tt[i] + (tt[i+1] - tt[i])*abs(hh[i])/(abs(hh[i]) +  abs(hh[i+1])) for i in rise_ends]
    set = [tt[i] + (tt[i+1] - tt[i])*abs(hh[i])/(abs(hh[i]) +  abs(hh[i+1])) for i in set_ends]
    return (rise, set)

## testing
test_200_years = [d for d in [dt.datetime.today() + dt.timedelta(days = x) for x in range(-36500, 36500)]]

# Meeus periodic terms tables (D, M, M', F, coefficient)

SIGMA_LR_TERMS= [
    (0, 0, 1, 0, 6288774, -20905355),
    (2, 0, -1, 0, 1274027, -3699111),
    (2, 0, 0, 0, 658314, -2955968),
    (0, 0, 2, 0, 213618, -569925),
    (0, 1, 0, 0, -185116, 48888),
    (0, 0, 0, 2, -114332, -3149),
    (2, 0, -2, 0, 58793, 246158),
    (2, -1, -1, 0, 57066, -152138),
    (2, 0, 1, 0, 53322, -170733),
    (2, -1, 0, 0, 45758, -204586),
    (0, 1, -1, 0, -40923, -129620),
    (1, 0, 0, 0, -34720, 108743),
    (0, 1, 1, 0, -30383, 104755),
    (2, 0, 0, -2, 15327, 10321),
    (0, 0, 1, 2, -12528, 0),
    (0, 0, 1, -2, 10980, 79661),
    (4, 0, -1, 0, 10675, -34782),
    (0, 0, 3, 0, 10034, -23210),
    (4, 0, -2, 0, 8548, -21636),
    (2, 1, -1, 0, -7888, 24208),
    (2, 1, 0, 0, -6766, 30824),
    (1, 0, -1, 0, -5163, -8379),
    (1, 1, 0, 0, 4987, -16675),
    (2, -1, 1, 0, 4036, -12831),
    (2, 0, 2, 0, 3994, -10445),
    (4, 0, 0, 0, 3861, -11650),
    (2, 0, -3, 0, 3665, 14403),
    (0, 1, -2, 0, -2689, -7003),
    (2, 0, -1, 2, -2602, 0),
    (2, -1, -2, 0, 2390, 10056),
    (1, 0, 1, 0, -2348, 6322),
    (2, -2, 0, 0, 2236, -9884),
    (0, 1, 2, 0, -2120, 5751),
    (0, 2, 0, 0, -2069, 0),
    (2, -2, -1, 0, 2048, -4950),
    (2, 0, 1, -2, -1773, 4130),
    (2, 0, 0, 2, -1595, 0),
    (4, -1, -1, 0, 1215, -3958),
    (0, 0, 2, 2, -1110, 0),
    (3, 0, -1, 0, -892, 3258),
    (2, 1, 1, 0, -810, 2616),
    (4, -1, -2, 0, 759, -1897),
    (0, 2, -1, 0, -713, -2117),
    (2, 2, -1, 0, -700, 2354),
    (2, 1, -2, 0, 691, 0),
    (2, -1, 0, -2, 596, 0),
    (4, 0, 1, 0, 549, -1423),
    (0, 0, 4, 0, 537, -1117),
    (4, -1, 0, 0, 520, -1571),
    (1, 0, -2, 0, -487, -1739),
    (2, 1, 0, -2, -399, 0),
    (0, 0, 2, -2, -381, -4421),
    (1, 1, 1, 0, 351, 0),
    (3, 0, -2, 0, -340, 0),
    (4, 0, -3, 0, 330, 0),
    (2, -1, 2, 0, 327, 0),
    (0, 2, 1, 0, -323, 1165),
    (1, 1, -1, 0, 299, 0),
    (2, 0, 3, 0, 294, 0),
    (2, 0, -1, -2, 0, 8752),
]

SIGMA_B_TERMS = [
    (0, 0, 0, 1, 5128122),
    (0, 0, 1, 1, 280602),
    (0, 0, 1, -1, 277693),
    (2, 0, 0, -1, 173237),
    (2, 0, -1, 1, 55413),
    (2, 0, -1, -1, 46271),
    (2, 0, 0, 1, 32573),
    (0, 0, 2, 1, 17198),
    (2, 0, 1, -1, 9266),
    (0, 0, 2, -1, 8822),
    (2, -1, 0, -1, 8216),
    (2, 0, -2, -1, 4324),
    (2, 0, 1, 1, 4200),
    (2, 1, 0, -1, -3359),
    (2, -1, -1, 1, 2463),
    (2, -1, 0, 1, 2211),
    (2, -1, -1, -1, 2065),
    (0, 1, -1, -1, -1870),
    (4, 0, -1, -1, 1828),
    (0, 1, 0, 1, -1794),
    (0, 0, 0, 3, -1749),
    (0, 1, -1, 1, -1565),
    (1, 0, 0, 1, -1491),
    (0, 1, 1, 1, -1475),
    (0, 1, 1, -1, -1410),
    (0, 1, 0, -1, -1344),
    (1, 0, 0, -1, -1335),
    (0, 0, 3, 1, 1107),
    (4, 0, 0, -1, 1021),
    (4, 0, -1, 1, 833),
    (0, 0, 1, -3, 777),
    (4, 0, -2, 1, 671),
    (2, 0, 0, -3, 607),
    (2, 0, 2, -1, 596),
    (2, -1, 1, -1, 491),
    (2, 0, -2, 1, -451),
    (0, 0, 3, -1, 439),
    (2, 0, 2, 1, 422),
    (2, 0, -3, -1, 421),
    (2, 1, -1, 1, -366),
    (2, 1, 0, 1, -351),
    (4, 0, 0, 1, 331),
    (2, -1, 1, 1, 315),
    (2, -2, 0, -1, 302),
    (0, 0, 1, 3, -283),
    (2, 1, 1, -1, -229),
    (1, 1, 0, -1, 223),
    (1, 1, 0, 1, 223),
    (0, 1, -2, -1, -220),
    (2, 1, -1, -1, -220),
    (1, 0, 1, 1, -185),
    (2, -1, -2, -1, 181),
    (0, 1, 2, 1, -177),
    (4, 0, -2, -1, 176),
    (4, -1, -1, -1, 166),
    (1, 0, 1, -1, -164),
    (4, 0, 1, -1, 132),
    (1, 0, -1, -1, -119),
    (4, -1, 0, -1, 115),
    (2, -2, 0, 1, 107),
]
