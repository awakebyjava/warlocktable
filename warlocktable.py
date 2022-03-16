
import pygame
import random
import RPi.GPIO as GPIO
import time
import pn532.pn532 as nfc
import csv
from pn532 import *
from pixelblaze import *

pn532 = PN532_SPI(debug=False, reset=20, cs=4)

ic, ver, rev, support = pn532.get_firmware_version()

pn532.SAM_configuration()

pygame.mixer.init()

if __name__ == "__main__":

    pixelblazeIP = "10.1.10.165"     # insert your own IP address here

    basicPatternName = "KITT"         # everybody has KITT!

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

    #print('This card is')
    #if uid == test1:
        #print('TEST CARD 1')
        #pb.setActivePattern(TableTest1)
        #pygame.mixer.music.stop()
        #pygame.mixer.music.load('/home/pi/Documents/MagicTarot/Ov/outre.wav')
        #pygame.mixer.music.play(-1);

    with open('warlocktable.csv') as csv_file:
        csv_reader = csv.reader(csv_file, delimiter=',')
        line_count = 0
        for row in csv_reader:
                print(f'\t{row[0]} has byte array {row[1]}')
                line_count += 1
        print(f'Processed {line_count} lines.')

GPIO.cleanup()
