import operator


def checksum(sentence):
    cksum = reduce(operator.xor, (ord(s) for s in sentence[1:-1]))
    return "%s%s" % (sentence, hex(cksum)[2:4].upper())
