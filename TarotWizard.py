
import pygame
import random
import RPi.GPIO as GPIO
import time
import pn532.pn532 as nfc

from pn532 import *

test2 = bytearray(b'\x04\xf00\x1a\xcfO\x80')
test1 = bytearray(b'\x04:7\x1a\xcfO\x81')
magician = bytearray(b'\x049i\x9afp\x81')
aceofpentacles = bytearray(b'\x049h\x9afp\x81')
thedevil = bytearray(b'\x049g\x9afp\x81')
wheeloffortune = bytearray(b'\x049f\x9afp\x81')
death = bytearray(b'\x049j\x9afp\x81')
forest = bytearray(b'\x049e\x9afp\x81')
plains = bytearray(b'\x049c\x9afp\x81')
swamp = bytearray(b'\x049b\x9afp\x81')
island = bytearray(b'\x049a\x9afp\x81')
mountain = bytearray(b'\x049d\x9afp\x81')

pn532 = PN532_SPI(debug=False, reset=20, cs=4)

ic, ver, rev, support = pn532.get_firmware_version()

# Configure PN532 to communicate with NTAG215 cards
pn532.SAM_configuration()

pygame.mixer.init()

from pixelblaze import *

if __name__ == "__main__":

    pixelblazeIP = "10.1.10.165"     # insert your own IP address here
    
    basicPatternName = "KITT"         # everybody has KITT!
    TableTest1 = "blink fade"  # a pattern with exported variables
    TableTest2 = "fireflies"
    magicianPattern = "green ripple reflections"
    aceofpentaclesPattern = "glitchbands"
    thedevilPattern = "sparkfire"
    wheeloffortunePattern = "spin cycle"
    deathPattern = "opposites"
    forestPattern = "GreenCard"
    swampPattern = "BlackCard"
    mountainPattern = "RedCard"
    islandPattern = "BlueCard"
    plainsPattern = "WhiteCard"
    
    # create a PixelblazeEnumerator object, listen for a couple of seconds, then
    # list the Pixelblazes we found.
    pbList = PixelblazeEnumerator()
    print("Testing: PixelblazeEnumerator object created -- listening for Pixelblazes")

    print("Available Pixelblazes: ", pbList.getPixelblazeList())        
    
    # create a Pixelblaze object.
    pb = Pixelblaze(pixelblazeIP)   # use your own IP address here
    pb.stopSequencer()              # make sure the sequencer isn't running    
    print("Testing: Pixelblaze object created,connected,ready!")
    
    print("Testing: setActivePattern")
    pb.setActivePattern("*OBVIOUSLY BOGUS PATTERN*")  # just to make sure nothing bad happens
    pb.setActivePattern(basicPatternName)


while True:
    print('Waiting for RFID/NFC card to write to!')
    while True:
        # Check if a card is available to read
        uid = pn532.read_passive_target(timeout=0.5)
        print('.', end="")
        # Try again if no card is available.
        if uid is not None:
            break
    print('Found card with UID:', [hex(i) for i in uid])

    print('This card is')
    if uid == test1:
        print('TEST CARD 1')
        pb.setActivePattern(TableTest1)
        pygame.mixer.music.stop()
        pygame.mixer.music.load('/home/pi/Documents/MagicTarot/Ov/outre.wav')
        pygame.mixer.music.play(-1);
    elif uid == test2:
        print('TEST CARD 2')
        pb.setActivePattern(TableTest2)
        pygame.mixer.music.stop()
        pygame.mixer.music.load('/home/pi/Documents/MagicTarot/Ov/cigarette.wav')
        pygame.mixer.music.play(-1);
    elif uid == magician:
        print('MAGICIAN')
        pb.setActivePattern(magicianPattern)
        pygame.mixer.music.stop()
        pygame.mixer.music.load('/home/pi/Documents/MagicTarot/Ov/crowley.wav')
        pygame.mixer.music.play(-1);
    elif uid == aceofpentacles:
        print('ACEOFPENTACLES')
        pb.setActivePattern(aceofpentaclesPattern)
        pygame.mixer.music.stop()
        pygame.mixer.music.load('/home/pi/Documents/MagicTarot/Ov/peromyscus.wav')
        pygame.mixer.music.play(-1);
    elif uid == thedevil:
        print('THEDEVIL')
        pb.setActivePattern(thedevilPattern)
        pygame.mixer.music.stop()
        pygame.mixer.music.load('/home/pi/Documents/MagicTarot/Ov/javan.wav')
        pygame.mixer.music.play(-1);
    elif uid == wheeloffortune:
        print('WHEELOFFORTUNE')
        pb.setActivePattern(wheeloffortunePattern)
        pygame.mixer.music.stop()
        pygame.mixer.music.load('/home/pi/Documents/MagicTarot/Ov/audley.wav')
        pygame.mixer.music.play(-1);
    elif uid == death:
        print('DEATH')
        pb.setActivePattern(deathPattern)
        pygame.mixer.music.stop()
        pygame.mixer.music.load('/home/pi/Documents/MagicTarot/Ov/september.wav')
        pygame.mixer.music.play(-1);
    elif uid == forest:

        pb.setActivePattern(forestPattern)
        #pygame.mixer.music.stop()
        #pygame.mixer.music.load('/home/pi/Documents/MagicTarot/MagicCards/forest.wav')
        #pygame.mixer.music.play(-1);
    elif uid == island:

        pb.setActivePattern(islandPattern)
        #pygame.mixer.music.stop()
        #pygame.mixer.music.load('/home/pi/Documents/MagicTarot/MagicCards/island.wav')
        #pygame.mixer.music.play(-1);
    elif uid == mountain:

        pb.setActivePattern(mountainPattern)
        #pygame.mixer.music.stop()
        #pygame.mixer.music.load('/home/pi/Documents/MagicTarot/MagicCards/mountain.wav')
        #pygame.mixer.music.play(-1);
    elif uid == swamp:

        pb.setActivePattern(swampPattern)
        #pygame.mixer.music.stop()
        #pygame.mixer.music.load('/home/pi/Documents/MagicTarot/MagicCards/swamp.wav')
        #pygame.mixer.music.play(-1);
    elif uid == plains:

        pb.setActivePattern(plainsPattern)
        #pygame.mixer.music.stop()
        #pygame.mixer.music.load('/home/pi/Documents/MagicTarot/MagicCards/plains.wav')
        #pygame.mixer.music.play(-1);
    else:
        print('not a registered card!')
    time.sleep(1)
    
GPIO.cleanup()