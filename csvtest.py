import csv

testa = bytearray(b'\x049b\x9afp\x81')

with open('warlocktable.csv') as csv_file:
    csv_reader = csv.reader(csv_file, delimiter=',')
    line_count = 0
    for row in csv_reader:
            uid = row[1]
            if uid == testa:
                print(uid)
                print('Your card is',row[0])
            else:
                print(uid)
                print(row[0],'is not your card')
                line_count += 1
    print(f'Processed {line_count} lines.')
