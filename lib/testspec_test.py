from . import testspec


def test_testspec():
    # yapf: disable
    tests = [
        (
            'pytest sanity/test.py',
            ' 180 pytest sanity/test.py'
        ),
        (
            'pytest sanity/state_sync_routed.py manytx 115',
            ' 180 pytest sanity/state_sync_routed.py manytx 115'
        ),
        (
            'pytest --timeout=180 sanity/test.py',
            ' 180 pytest sanity/test.py'
        ),
        (
            'pytest --timeout=420 sanity/test.py',
            ' 420 pytest --timeout=420 sanity/test.py'
        ),
        (
            'pytest --release sanity/test.py',
            ' 180 pytest --release sanity/test.py'
        ),
        (
            'pytest --remote sanity/test.py',
            '1080 pytest --remote sanity/test.py'
        ),
        (
            'pytest --timeout=420 --release --remote sanity/test.py',
            '1320 pytest --timeout=420 --release --remote sanity/test.py'
        ),
        (
            'pytest sanity/test.py --features foo,bar --features=baz',
            ' 180 pytest sanity/test.py --features=bar,baz,foo'
        ),
        (
            'pytest sanity/test.py --features foo,adversarial --features=foo',
            ' 180 pytest sanity/test.py --features=foo'
        ),
        (
            'pytest --timeout 420 sanity/test.py',
            'Err: Invalid argument ‘--timeout’'
        ),
        (
            'pytest --invalid-flag sanity/test.py',
            'Err: Invalid argument ‘--invalid-flag’'
        ),
        (
            'pytest',
            'Err: Missing test argument'
        ),
        (
            'pytest sanity/test.py --features=`rm-rf`',
            'Err: Invalid feature ‘`rm-rf`’'
        ),
        (
            'pytest /bin/destroy-the-world.py',
            ' 180 pytest /bin/destroy-the-world.py'
        ),
        (
            'pytest ../../bin/destroy-the-world.py',
            'Err: Invalid test name ‘../../bin/destroy-the-world.py’'
        ),
        (
            'mocknet mocknet/sanity.py',
            ' 180 mocknet mocknet/sanity.py'
        ),
        (
            'expensive nearcore test_tps test::test_highload',
            ' 180 expensive nearcore test_tps test::test_highload'
        ),
        (
            'expensive nearcore test_tps test::test_highload --features=foo',
            ' 180 expensive nearcore test_tps test::test_highload --features=foo'
        ),
        (
            'expensive nearcore /bin/destroy test::test_highload',
            'Err: Invalid test name ‘/bin/destroy’'
        ),
        (
            'expensive nearcore test_tps',
            'Err: expensive test category requires three arguments: '
            '<package> <test-executable> <test-name>'
        ),
        (
            'expensive nearcore',
            'Err: expensive test category requires three arguments: '
            '<package> <test-executable> <test-name>'
        ),
        (
            'expensive nearcore test_tps test::test_highload bogus',
            'Err: expensive test category requires three arguments: '
            '<package> <test-executable> <test-name>'
        ),
        (
            'invalid-category sanity/test.py',
            'Err: Invalid category ‘invalid-category’'
        ),
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
            got.append(f'{count} × {spec.name()}')
        except ValueError as ex:
            msg = str(ex)
            if (pos := msg.find(' in test ')) != -1:
                msg = msg[:pos]
            got.append(f'Err: {msg}')
    assert want == got


def test_testspec_timeout():
    # yapf: disable
    tests = {
        'pytest sanity/test.py': (
            180,
            180,
            'pytest sanity/test.py',
            'pytest sanity/test.py',
            'pytest --timeout=180 sanity/test.py'
        ),
        'pytest --timeout=180 sanity/test.py': (
            180,
            180,
            'pytest sanity/test.py',
            'pytest sanity/test.py',
            'pytest --timeout=180 sanity/test.py'
        ),
        'pytest --timeout=240 sanity/test.py': (
            240,
            240,
            'pytest --timeout=240 sanity/test.py',
            'pytest sanity/test.py',
            'pytest --timeout=240 sanity/test.py'
        ),
        'pytest --remote sanity/test.py': (
            180,
            1080,
            'pytest --remote sanity/test.py',
            'pytest --remote sanity/test.py',
            'pytest --timeout=180 --remote sanity/test.py'
        ),
    }
    # yapf: enable
    for line, want in tests.items():
        spec = testspec.TestSpec(line)
        got = (
            spec.timeout,
            spec.full_timeout,
            spec.name(),
            spec.name(include_timeout=False),
            spec.name(include_timeout=True)
        )
        assert want == got
