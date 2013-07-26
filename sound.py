#!/usr/bin/env python
import time, os, sys
import glob
import subprocess
from pyfirmata import Arduino, util
import itertools
import random
import threading
from Queue import Queue

SOUND_ROOT = '/home/pi/FLG_sounds'
INHALE_SOUNDS = glob.glob( os.path.join(SOUND_ROOT, 'normalized/inhale_[0-9]*.wav' ) )
EXHALE_SOUNDS = glob.glob( os.path.join(SOUND_ROOT, 'normalized/exhale_[0-9]*.wav' ) )
MIN_BREATH_SPEED = 0.6
MAX_BREATH_SPEED = 2.5
GROWTH_LIMIT=0.0003
DECAY_RATE=1.0

IR_PINS = [0, 1]
#IR_EVENT_THRESHOLD = 0.05
IR_EVENT_THRESHOLD = 0.2

FELT_PINS = [5]

def median(mylist):
    sorts = sorted(mylist)
    length = len(sorts)
    if not length % 2:
        return (sorts[length / 2] + sorts[length / 2 - 1]) / 2.0
    return sorts[length / 2]

def play_sound(filename, speed=1.0, vol=1.0, block=False):
    filename = os.path.join(SOUND_ROOT, filename)
    print "Playing %s" % filename
    out = open('/dev/null', 'w')
    #out = None
    p = subprocess.Popen(('play',filename, 'tempo', str(speed), 'vol', str(vol)), stdout=out, stderr=out)
    #p = subprocess.Popen("sleep 1", stdout=out, stderr=out)
    if block:
        p.wait()
    return p


def readIR(analog_pin):
    SAMPLES = 8
    while True:
        samples = []
        while len(samples) < SAMPLES:
           sample = board.analog[analog_pin].read()
           if sample:
               samples.append(sample)
        return median(samples)

def gen_breathing_sounds():
    while True:
        yield random.choice(INHALE_SOUNDS)   
        yield random.choice(EXHALE_SOUNDS)   


breathspeed = 0.8 
class Breather(threading.Thread):
    def __init__(self, queue, *args, **kwargs):
        super(Breather, self).__init__(*args, **kwargs)
        self.daemon = True
        self.speed = 0.8
        self.queue = queue

    def run(self):
        while True:
            while not self.queue.empty():
                self.speed = self.queue.get()
            #print "Breathing speed: %f" % self.speed
            play_sound(breathing_sounds.next(), speed=self.speed, block=True)

    @classmethod
    def counter_to_speed(klass, counter):
        return float(counter.value) / float(counter.max_value) * (MAX_BREATH_SPEED - MIN_BREATH_SPEED) + MIN_BREATH_SPEED

class Looper(threading.Thread):
    def __init__(self, soundfile, speed=1.0, vol=1.0, *args, **kwargs):
        super(Looper, self).__init__(*args, **kwargs)
        self.daemon = True
        self.speed = speed
        self.vol = vol
        self.soundfile = soundfile
        

    def run(self):
        while True:
            play_sound(self.soundfile, speed=self.speed, vol=self.vol, block=True)
            time.sleep(0.10)

class ActivityCounter(object):
    def __init__(self, max_value=60, growth_limit=GROWTH_LIMIT, decay_rate=DECAY_RATE):
        self.value = 0
        self.max_value = max_value

        self.decay_rate = decay_rate # in seconds
        self.growth_limit = growth_limit # in seconds

        self.last_decay_time = time.time()
        self.last_grow_time = time.time()

    def update(self):
        if time.time() - self.last_decay_time > self.decay_rate:
            if self.value > 0:
                self.value -= 1
            self.last_decay_time = time.time()
        print "Counter: %d" % int(self)
        sys.stdout.flush()

    def __iadd__(self, n):
        if time.time() - self.last_grow_time > self.growth_limit:
            while self.value < self.max_value and n > 0:
                self.value += 1
                n -= 1
            self.last_grow_time = time.time()
        return self

    def __isub__(self, n):
        self.value -= n
        return self

    def __int__(self):
        return self.value

class IRSensor(object):
    def __init__(self, pin, counter):
        self.pin = pin
        self.value = 0.0
        self.prior_value = 0.0
        self.counter = counter
        print "IR Sensor on analog %d" % pin

    def update(self):
        self.prior_value = self.value
        if board: # if no arduino is hooked up, skip this
            self.value = readIR(self.pin)
        delta = self.value - self.prior_value
        if delta > IR_EVENT_THRESHOLD:
            self.counter += 1
            print "IR %d delta: %f" % (self.pin, self.value - self.prior_value)

class FeltSensor(object):
    def __init__(self, pin):
        self.pin = pin
        self.value = 0
        self.last_value = 0
        self.sounds = glob.glob( os.path.join(SOUND_ROOT, 'ddt_stem_sounds/Stem*.wav') )

    def update(self):
        self.last_value = self.value
        r = readIR(self.pin)
        self.value = {True: 1, False:0}[r >= 0.9]
        #print "Felt %d: %F" % (self.pin, self.value)
        if self.last_value == 0 and self.value == 1:
            self.trigger_sound()

    def trigger_sound(self):
        soundfile = random.choice(self.sounds)
        play_sound(soundfile, vol="5dB" )



if __name__ == '__main__':

    # Setup pyfirmata for arduino reads
    acm_no = 0
    board = None
    while acm_no < 10:
        try:
            board = Arduino('/dev/ttyACM%d' % acm_no)
            print "Found arduino on /dev/tty/ACM%d" % acm_no
            break
        except:
            acm_no += 1
            continue
    if board:
        it = util.Iterator(board)
        it.daemon = True
        it.start()
        for pin in IR_PINS + FELT_PINS:
            board.analog[pin].enable_reporting()

    breathing_sounds = gen_breathing_sounds()

    speedqueue = Queue()
    breather = Breather(speedqueue)
    breather.start()

    scraper = Looper('normalized/scrapes_loop.wav', vol='-3dB')
    scraper.start()
    
    counter = ActivityCounter()
    ir_sensors = [ IRSensor(pin, counter) for pin in IR_PINS  ]
    felt_sensors = [ FeltSensor(pin) for pin in FELT_PINS ]
    
    speed = 0.8
    while True:
        for irs in ir_sensors:
            irs.update()
        counter.update()
        #print("Speed: %f" % Breather.counter_to_speed(counter))
        speedqueue.put(Breather.counter_to_speed(counter))

        for felt in felt_sensors:
            felt.update()
        
        time.sleep(0.10)
