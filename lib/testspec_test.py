from __future__ import annotations

from . import testspec


def test_testspec():
    invalid_expensive = ('Err: expensive test category requires three '
                         'arguments: <package> <test-executable> <test-name>')
    # yapf: disable
    tests = [
        ('pytest sanity/test.py',
         ' 180 pytest --timeout=3m sanity/test.py'),
        ('pytest sanity/state_sync_routed.py manytx 115',
         ' 180 pytest --timeout=3m sanity/state_sync_routed.py manytx 115'),
        ('pytest --timeout=180 sanity/test.py',
         ' 180 pytest --timeout=3m sanity/test.py'),
        ('pytest --timeout=420 sanity/test.py',
         ' 420 pytest --timeout=7m sanity/test.py'),
        ('pytest --release sanity/test.py',
         ' 180 pytest --timeout=3m --release sanity/test.py'),
        ('pytest --remote sanity/test.py',
         '1080 pytest --timeout=3m --remote sanity/test.py'),
        ('pytest --skip-build sanity/test.py',
         ' 180 pytest --skip-build --timeout=3m sanity/test.py'),
        ('pytest --timeout=420 --release --remote sanity/test.py',
         '1320 pytest --timeout=7m --release --remote sanity/test.py'),
        ('pytest --timeout=420 --release --remote --skip-build s/test.py',
         '1320 pytest --skip-build --timeout=7m --release --remote s/test.py'),
        ('pytest sanity/test.py --features foo,bar --features=baz',
         ' 180 pytest --timeout=3m sanity/test.py --features bar,baz,foo'),
        ('pytest sanity/test.py --features foo,adversarial --features=foo',
         ' 180 pytest --timeout=3m sanity/test.py --features foo'),
        ('pytest --timeout 420 sanity/test.py',
         'Err: Invalid argument ‘--timeout’'),
        ('pytest --invalid-flag sanity/test.py',
         'Err: Invalid argument ‘--invalid-flag’'),
        ('pytest',
         'Err: Missing test argument'),
        ('pytest sanity/test.py --features=`rm-rf`',
         'Err: Invalid feature ‘`rm-rf`’'),
        ('pytest /bin/destroy-the-world.py',
         ' 180 pytest --timeout=3m /bin/destroy-the-world.py'),
        ('pytest ../../bin/destroy-the-world.py',
         'Err: Invalid test name ‘../../bin/destroy-the-world.py’'),
        ('mocknet mocknet/sanity.py',
         ' 180 mocknet --skip-build --timeout=3m mocknet/sanity.py'),
        ('mocknet --skip-build mocknet/sanity.py',
         ' 180 mocknet --skip-build --timeout=3m mocknet/sanity.py'),
        ('expensive nearcore test_tps test::test_highload',
         ' 180 expensive --timeout=3m nearcore test_tps test::test_highload'),
        ('expensive nearcore test_tps test::test_highload --features=foo',
         ' 180 expensive --timeout=3m nearcore test_tps test::test_highload --features foo'),
        ('expensive nearcore /bin/destroy test::test_highload',
         'Err: Invalid test name ‘/bin/destroy’'),
        ('expensive nearcore test_tps',
         invalid_expensive),
        ('expensive nearcore',
         invalid_expensive),
        ('expensive nearcore test_tps test::test_highload bogus',
         invalid_expensive),
        ('invalid-category sanity/test.py',
         'Err: Invalid category ‘invalid-category’'),
    ]
    # yapf: enable
    got = []
    want = []
    for line, expected in tests:
        want.append(expected)
        try:
            spec = testspec.TestSpec(line)
            got.append(f'{spec.full_timeout:>4} {spec}')
        except ValueError as ex:
            msg = str(ex)
            if (pos := msg.find(' in test ')) != -1:
                msg = msg[:pos]
            got.append(f'Err: {msg}')
    assert want == got


def test_testspec_with_count():
    # yapf: disable
    tests = {
        'pytest sanity/test.py'    : '1 × pytest sanity/test.py',
        '1 pytest sanity/test.py'  : '1 × pytest sanity/test.py',
        '0 pytest sanity/test.py'  : '0 × pytest sanity/test.py',
        ' 5  pytest sanity/test.py': '5 × pytest sanity/test.py',
        '-1 pytest sanity/test.py' : 'Err: Invalid category ‘-1’',
    }
    # yapf: enable
    got = []
    want = []
    for line, expected in tests.items():
        want.append(expected)
        try:
            count, spec = testspec.TestSpec.from_name_with_count(line)
            got.append(f'{count} × {spec.short_name}')
        except ValueError as ex:
            msg = str(ex)
            if (pos := msg.find(' in test ')) != -1:
                msg = msg[:pos]
            got.append(f'Err: {msg}')
    assert want == got


class MockTestRow(testspec.TestDBRow):

    def __init__(self,
                 name: str,
                 timeout: int = 0,
                 skip_build: bool = False) -> MockTestRow:
        super().__init__()
        self.name = name
        self.timeout = timeout
        self.skip_build = skip_build


def test_from_row():
    # yapf: disable
    tests = (
        (  0, False, 'pytest --timeout=3m dir/test.py'),
        (180, False, 'pytest --timeout=3m dir/test.py'),
        (180, True,  'pytest --skip-build --timeout=3m dir/test.py'),
    )
    # yapf: enable
    for timeout, skip_build, want_full_name in tests:
        row = MockTestRow('pytest dir/test.py', timeout, skip_build)
        spec = testspec.TestSpec.from_row(row)
        assert want_full_name == spec.full_name


def test_testspec_name():
    # yapf: disable
    tests = {
        'pytest sanity/test.py': (
            180,
            180,
            'pytest sanity/test.py',
            'pytest --timeout=3m sanity/test.py'
        ),
        'pytest --timeout=180 sanity/test.py': (
            180,
            180,
            'pytest sanity/test.py',
            'pytest --timeout=3m sanity/test.py'
        ),
        'pytest --skip-build sanity/test.py': (
            180,
            180,
            'pytest sanity/test.py',
            'pytest --skip-build --timeout=3m sanity/test.py'
        ),
        'pytest --remote sanity/test.py': (
            180,
            1080,
            'pytest --remote sanity/test.py',
            'pytest --timeout=3m --remote sanity/test.py'
        ),
    }
    # yapf: enable
    for line, want in tests.items():
        spec = testspec.TestSpec(line)
        got = (spec.timeout, spec.full_timeout, spec.short_name, spec.full_name)
        assert want == got
