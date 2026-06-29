def helper():
    return 1


def top():
    helper()
    print("x")
    other.thing()


class C:
    def a(self):
        return self.b()

    def b(self):
        helper()
        return 2


C().a()
