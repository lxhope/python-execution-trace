from execution_trace.record import record


@record(3)
def foo(x, y):
    a = x + y
    for i in range(a):
        x = x + 1
    return x


if __name__ == '__main__':
    print foo(1, 3)
    print foo(2, 4)
    print foo(3, 5)
