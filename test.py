


def gen():
    while True:
        (yield)


g = gen()
# next(g)
g.send("Test")

print(next(g))