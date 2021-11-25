import dataclasses
import re
import typing

_DEFAULT_TIMEOUT = 180
_VALID_FEATURE_RE = re.compile(r'^[a-zA-Z0-9_][-a-zA-Z0-9_]*$')


class _CategorySpec(typing.NamedTuple):
    """Test category specification, i.e. category and its flags."""
    category: str
    timeout: int
    is_release: bool
    is_remote: bool
    skip_build: bool


_TIME_SUFFIXES = {'h': 3600, 'm': 60, 's': 1}


def _parse_timeout(timeout: str) -> int:
    """Parses timeout interval and converts it into number of seconds.

    Args:
        timeout: An integer with an optional ‘h’, ‘m’ or ‘s’ suffix which
            multiply the integer by 3600, 60 and 1 respectively.
    Returns:
        Interval in seconds.
    Raises:
        ValueError: if the string argument is in the wrong format.
    """
    try:
        mul = _TIME_SUFFIXES.get(timeout[-1])
        if mul:
            timeout = timeout[:-1]
        else:
            mul = 1
        return int(timeout) * mul
    except (ValueError, IndexError) as ex:
        raise ValueError(f'Invalid timeout argument ‘{timeout}’') from ex


def _format_timeout(timeout: int) -> str:
    """Formats timeout expressed in seconds as a string with optional suffix.

    Args:
        timeout: An interval in seconds.
    Returns:
        Interval formatted as a string potentially with ‘h’ or ‘m’ suffix.
        Suffixes are used if interval represents integer number of hours or
        minutes respectively and largest possible suffix is used.
    """
    if timeout % 3600 == 0:
        return f'{timeout // 3600}h'
    if timeout % 60 == 0:
        return f'{timeout // 60}m'
    return str(timeout)


def _extract_category(words: typing.List[str]) -> _CategorySpec:
    """Extracts category specification from a test.

    Expects words in the format:

        <category> [--timeout=<timeout>] [--skip-build] [--release] [--remote] <args>...

    Args:
        words: The test as list of words.  The list is modified in place by
            removing category and category flags from it.
    Returns:
        Category specification extracted from the arguments.
    Raises:
        ValueError: If test has invalid category specification, <args> are
            missing or contain test name which does not appear valid.
    """
    category = None
    timeout = _DEFAULT_TIMEOUT
    is_release = False
    is_remote = False
    skip_build = False

    index = 0  # silence pylint warning
    for index, word in enumerate(words):
        if not index:
            category = word
        elif word == '--release':
            is_release = True
        elif word == '--remote':
            is_remote = True
        elif word == '--skip-build':
            skip_build = True
        elif word.startswith('--timeout='):
            timeout = _parse_timeout(word[10:])
        elif word.startswith('--'):
            raise ValueError(f'Invalid argument ‘{word}’')
        else:
            break
    else:
        raise ValueError('Missing test argument')

    if category is None:
        raise ValueError('Empty specification')
    if category not in ('pytest', 'mocknet', 'expensive'):
        raise ValueError(f'Invalid category ‘{category}’')

    words[:index] = ()

    return _CategorySpec(category=category,
                         timeout=timeout,
                         is_release=is_release,
                         is_remote=is_remote,
                         skip_build=skip_build or category == 'mocknet')


def _extract_features(words: typing.List[str]) -> str:
    """Extracts features from a test.

    Expects words in the format:

        <args>... [(--features=<features> | --features <features>)...

    Args:
        words: The test as list of words with category specification extracted.
            The list is modified in place by removing category and category
            flags from it.
    Returns:
        Comma-separated list of features extracted from the arguments or empty
        string if there were no features.  The list is normalised: duplicates
        are removed, ‘adversarial’ and ‘test_features’ features are removed
        (since they are always included) and features are sorted.
    Raises:
        ValueError: If features arguments are invalid or any of the feature is
            invalid.
    """
    start = None
    want_features = False
    features = set()
    for index, word in enumerate(words):
        if want_features:
            features.update(word.split(','))
            want_features = False
        elif word.startswith('--features='):
            if start is None:
                start = index
            features.update(word[11:].split(','))
        elif word == '--features':
            if start is None:
                start = index
            want_features = True

    if start is None:
        return ''

    # ‘adversarial’/‘test_features’ and ‘rosetta_rpc’ features are always
    # enabled so remove them from the set user chosen.  If we don’t do that, we
    # may end up doing an unnecessary build.
    features.discard('adversarial')
    features.discard('test_features')
    features.discard('rosetta_rpc')

    if want_features:
        raise ValueError('Missing features after --feature argument')
    for feature in features:
        if not _VALID_FEATURE_RE.search(feature):
            raise ValueError(f'Invalid feature ‘{feature}’')

    words[start:] = ()
    return ','.join(sorted(features))


def _check_args(category: str, args: typing.Sequence[str]) -> None:
    """Verifies whether test arguments for given category look valid.

    For expensive category checks that there are exactly three arguments and
    that the second one looks like test executable name.  For mocknet and pytest
    category checks that the first argument looks like a path to a python script
    inside of the pytest directory in the repository.

    Args:
        category: ‘expensive’, ‘mocknet’ or ‘pytest’ specifying test category.
        args: Test arguments for the category.
    Raises:
        ValueError: If validation fails.
    """
    if category == 'expensive':
        if len(args) != 3:
            raise ValueError(
                'expensive test category requires three arguments: '
                '<package> <test-executable> <test-name>')
        pattern = '^[-_a-zA-Z0-9]+$'
        name = args[1]
    else:
        assert category in ('mocknet', 'pytest')
        pattern = r'^[-_a-zA-Z0-9/]+\.py$'
        name = args[0]
    if not re.search(pattern, name):
        raise ValueError(f'Invalid test name ‘{name}’')


TestSpecSequence = typing.Sequence['TestSpec']


class TestDBRow:
    name: str
    timeout: int
    skip_build: bool


@dataclasses.dataclass(frozen=True)
class TestSpec:
    """Specification for a test to be run.

    Attributes:
        category: The test category such as pytest, mocknet or expensive.
        timeout: Timeout to use for the test excluding any additional provisions
            for remote tests.  If ‘--timeout’ was specified in test spec this
            value comes from that category argument otherwise it’s the default
            three minutes.
        is_release: Whether the test uses release build.  True if ‘--release’
            was present in test spec.
        is_remote: Whether the test runs remotely.  True if ‘--remote’ was
            present in test spec.
        args: The test arguments past the category and category flags excluding
            any features.  The exact format of the arguments depends on the test
            category.
        features: Build features to include in the neard binary.
    """
    category: str
    timeout: int
    is_release: bool
    is_remote: bool
    skip_build: bool
    args: typing.Sequence[str]
    features: str

    def __init__(self, name: str) -> None:
        """Parses a test name.

        Checks that the test is a string and verifies that the --features (if
        any) arguments are correct.  That is, if there's a --features switch in
        the test, everything that follows it must be features and more
        --features switches.  Furthermore, all features must have valid names.

        Note that many things about the test are not checked.  Features are
        checked because they are passed somewhat verbatim to cargo commands and
        we want to control what goes there.  We are less concerned about
        arguments to tests.

        Args:
            name: The test name.
        Returns:
            A TestSpec describing the test.
        Raises:
            ValueError: if `name` is an invalid test specification.
        """
        words = name.split()
        try:
            category_spec = _extract_category(words)
            features = _extract_features(words)
            _check_args(category_spec.category, words)
        except ValueError as ex:
            raise ValueError(f'{ex} in test ‘{name}’') from ex
        object.__setattr__(self, 'category', category_spec.category)
        object.__setattr__(self, 'timeout', category_spec.timeout)
        object.__setattr__(self, 'is_release', category_spec.is_release)
        object.__setattr__(self, 'is_remote', category_spec.is_remote)
        object.__setattr__(self, 'skip_build', category_spec.skip_build)
        object.__setattr__(self, 'args', tuple(words))
        object.__setattr__(self, 'features', features)

    @classmethod
    def from_name_with_count(cls, name: str) -> typing.Tuple[int, 'TestSpec']:
        """Parses a test name with an optional count prefix.

        This is essentially equivalent to `from_name` method with additional
        support for a numeric prefix in `name`.

        Args:
            name: The test name with optional integer prefix.
        Returns:
            A (count, spec) pair where first element is value of the optional
            integer prefix or 1 if the prefix was missing and the second is the
            TestSpec describing the test.
        Raises:
            ValueError: if `name` is an invalid test specification.
        """
        count = 1
        if match := re.search(r'^\s*(\d+)\s+(.+)$', name):
            count = int(match.group(1))
            name = match.group(2)
        return count, cls(name)

    @classmethod
    def from_row(cls, row: TestDBRow) -> 'TestSpec':
        """Construct test spec from a row read from the database.

        Args:
            row: A row read from the `tests` database table.
        Returns:
            A TestSpec describing the test.
        Raises:
            ValueError: if data read from the database is invalid.
        """
        self = cls(row.name)
        if (timeout := int(row.timeout)) >= 60:
            object.__setattr__(self, 'timeout', timeout)
        object.__setattr__(self, 'skip_build', bool(row.skip_build))
        return self

    @property
    def short_name(self) -> str:
        """Returns normalised short name of the test.

        Short name does not include --timeout or --skip-build flags."""
        return self._name(full=False)

    @property
    def full_name(self) -> str:
        """Returns normalised full name of the test."""
        return self._name(full=True)

    def _name(self, *, full: bool) -> str:
        """Returns normalised name of the test.

        Args:
            full: If False, the name will not include --timeout or --skip-build
                category flags.
        Returns:
            A normalised test specification.
        """
        result = [self.category]
        if full:
            if self.skip_build:
                result.append('--skip-build')
            result.append(f'--timeout={_format_timeout(self.timeout)}')
        if self.is_release:
            result.append('--release')
        if self.is_remote:
            result.append('--remote')
        result.extend(self.args)
        if self.features:
            result.append(f'--features {self.features}')
        return ' '.join(result)

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_timeout(self) -> int:
        """Timeout including provisions for remote tests."""
        return self.timeout + 15 * 60 * self.is_remote

    @property
    def build_dir(self) -> str:
        """Either ‘debug’ or ‘release’ depending where test binaries are."""
        if self.is_release:
            return 'release'
        return 'debug'
