# Contributing Guide

We welcome contributions to django-graphex! This guide will help you get started.

## Quick Start

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/your-username/django-graphex.git
   cd django-graphex
   ```
3. **Install development dependencies**:
   ```bash
   uv sync
   ```
4. **Create a branch** for your changes:
   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Setup

### Prerequisites

- Python 3.12, 3.13, or 3.14
- [uv](https://docs.astral.sh/uv/) for dependency management
- Git

!!! note "Python Version Requirement"
    The project requires Python 3.12 or higher. Make sure you have one of the supported versions installed.

### Installation

```bash
# Clone the repository
git clone https://github.com/eamigo86/django-graphex.git
cd django-graphex

# Install dependencies (into a managed venv)
uv sync

# Install pre-commit hooks (optional but recommended)
uv run pre-commit install
```

### Development Commands

We use `make` commands for common development tasks:

```bash
# Run tests
make test

# Run all tests across Python/Django versions
make test-all

# Code quality checks
make quality

# Security checks (Bandit + the frozen runtime dependency closure)
make security

# Audit an existing wheel without rebuilding it (CI supplies the wheel path)
uv run tox -e release-audit -- /path/to/django_graphex-*.whl

# Format code
make format

# Type checking
make type-check

# Build documentation
make docs

# Serve documentation locally
make docs-serve

# Clean build artifacts
make clean
```

The security environment exports the frozen runtime dependency closure from
`uv.lock` before running `pip-audit`. Development-only packages are excluded,
so findings describe what applications install rather than tox's audit tools.

## Code Standards

### Code Style

We use two tools to maintain code quality:

- **ruff** for formatting, import sorting and linting (`ruff format` + `ruff check`)
- **mypy** for type checking

Format and autofix locally, then run all quality checks:
```bash
make format    # ruff format + ruff check --fix
make quality   # ruff format --check + ruff check + mypy
```

### Documentation Standards

- All public classes and methods must have docstrings
- Use Google-style docstrings
- Include examples in docstrings where helpful
- Keep documentation up-to-date with code changes

During the progressive no-backtick migration, maintainers can run the checker
with `--strict-content` to apply DOC201 to every docstring owner. This opt-in is
temporary: the final gate will enforce the rule globally without a permanent
baseline. CI uses a merge-base ratchet so only changed owners and new Python
files must be clean while untouched debt remains; the ratchet is removed at
zero debt rather than preserving counts or suppressions.
Use `--strict-public` during migration; the legacy default stays until debt is
clear. Public means importable modules, non-underscore top-level names, private
top-level names in `__all__`, and non-private class members. Strict `Args:` must
be non-empty and exact, including `*args` and `**kwargs`.

#### Strict result sections

Use `Returns:` for ordinary non-`None` results and `Yields:` for generators.
Functions annotated as `None`, `NoReturn`, or `Never` have neither section.
Required result and `Raises:` sections must be non-empty; exceptions raised by
nested functions or classes belong to those nested owners. Keep every type in
the signature only—section entries describe names and behavior:

```python
def iter_ids(limit: int) -> Iterator[int]:
    """Yield identifiers up to a limit.

    Args:
        limit: Maximum number of identifiers.

    Yields:
        item: One identifier.
    """
    yield from range(limit)
```

### Testing Standards

- Follow strict **RED → GREEN → REFACTOR** for code, documentation, workflows
  and benchmark-harness changes.
- Write tests for every feature and regression.
- Keep branch coverage strictly above 95%; the root and changed-line floor is
  **95.01%**.
- Use descriptive test names
- Follow the existing test structure

The tool dependencies in `tox.ini` deliberately use bounded compatibility
ranges. Keep those ranges identical to their entries in
`dependency-groups.dev` in `pyproject.toml`; the dependency-contract test
rejects missing bounds and drift between local and CI environments. Add new
standalone CI tools, such as `diff-cover`, to the development group with both a
minimum supported version and an upper major-version bound.

### Test contract

Focused RED/GREEN commands must disable the repository-wide coverage options:

```bash
uv run pytest -q --no-cov tests/test_your_feature.py
```

Never erase `addopts` with `-o addopts=""`. After the focused loop, run the full
suite and enforce changed-line coverage from its report:

```bash
uv run pytest -q
uvx 'diff-cover>=10.5.1,<11' coverage.xml \
  --compare-branch=origin/main --fail-under=95.01
```

Assert the **exact exception** class and a stable message with `match=`; broad
`pytest.raises(Exception)` checks can hide unrelated failures:

```python
with pytest.raises(ImproperlyConfigured, match="permission hook returned"):
    build_schema()
```

```python
def test_django_list_object_type_pagination():
    """Test that DjangoListObjectType properly paginates results."""
    # Test implementation
    pass
```

## Making Changes

### 1. Choose What to Work On

- Check [open issues](https://github.com/eamigo86/django-graphex/issues)
- Look for issues labeled `good first issue` for beginners
- Propose new features by opening an issue first

### 2. Write Code

- Follow the code standards above
- Add tests for your changes
- Update documentation if needed
- Keep commits small and focused

### 3. Test Your Changes

```bash
# Run tests for your Python version
make test

# Run tests for all supported versions (takes longer)
make test-all

# Check code quality
make quality

# Check security
make security
```

### 4. Update Documentation

- Update docstrings for any changed APIs
- Add examples if you're adding new features
- Update the changelog if your change is user-facing

### 5. Submit a Pull Request

1. **Push your changes**:
   ```bash
   git push origin feature/your-feature-name
   ```

2. **Open a pull request** on GitHub

3. **Describe your changes** clearly in the PR description

4. **Wait for review** and address any feedback

## Pull Request Guidelines

### Title Format

Use conventional commit format:
- `feat: add new pagination option`
- `fix: resolve issue with nested mutations`
- `docs: improve installation guide`
- `test: add tests for directive validation`

### Description Template

```markdown
## Description
Brief description of what this PR does.

## Type of Change
- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update

## Testing
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] All new and existing tests pass locally
- [ ] I have run the full test suite (`make test-all`)

## Documentation
- [ ] I have updated the documentation accordingly
- [ ] I have updated the changelog if needed

## Checklist
- [ ] My code follows the style guidelines of this project
- [ ] I have performed a self-review of my code
- [ ] My changes generate no new warnings
- [ ] Any dependent changes have been merged and published
```

## Types of Contributions

### Bug Fixes

- Always include a test that reproduces the bug
- Explain the root cause in the PR description
- Consider edge cases

### New Features

- Discuss the feature in an issue first
- Include comprehensive tests
- Update documentation and examples
- Consider backward compatibility

### Documentation

- Keep language clear and concise
- Include practical examples
- Test code examples to ensure they work
- Update related documentation

### Performance Improvements

- Include benchmarks showing the improvement
- Ensure the change doesn't break existing functionality
- Consider memory usage as well as speed

## Development Tips

### Running Specific Tests

```bash
# Run tests for a specific file
uv run pytest tests/test_fields.py

# Run tests matching a pattern
uv run pytest -k "test_pagination"

# Run with coverage
uv run pytest --cov=django_graphex
```

### Debugging

```bash
# Run with ipdb for debugging
uv run pytest tests/test_fields.py -s --pdb
```

### Database Setup

SQLite remains the zero-setup default. Before publication, CI also runs the
transaction contract against **PostgreSQL 17** with Python 3.12 and Django 6.0.
To reproduce that gate against a local PostgreSQL service:

```bash
GDX_TEST_DATABASE=postgres \
POSTGRES_DB=django_graphex \
POSTGRES_USER=postgres \
POSTGRES_PASSWORD=postgres \
POSTGRES_HOST=127.0.0.1 \
POSTGRES_PORT=5432 \
uv run pytest -q --no-migrations --no-cov \
  tests/integration/test_postgresql_transactions.py
```

Every test in that module asserts `connection.vendor == "postgresql"`, so a
misconfigured run cannot silently pass on SQLite. MySQL is not part of this
reduced release gate.

## Release contract

Production publishing waits for the **complete validation graph**: the six
Python/Django combinations, base install, quality/security, root and patch
coverage, PostgreSQL 17, docs, playground and the release artifact.

The release-artifact job builds one **immutable artifact** containing the wheel,
sdist and `SHA256SUMS`. It checks the installed wheel outside the checkout,
including its `site-packages` origin and `py.typed`, then every publisher reuses
those bytes and must never rebuild them. See the full
[release process](releasing.md).

`workflow_dispatch` publishes only to TestPyPI. Production PyPI accepts only
`refs/tags/v*` whose version matches `pyproject.toml`; Pages deploys the docs
artifact validated before publication. A failed post-PyPI job is rerun for the
same immutable tag—never move or recreate it.

### Installed-wheel release gate

CI installs the candidate wheel under `$RUNNER_TEMP` and executes its smoke
check from outside the repository checkout with `PYTHONPATH` removed. The gate
requires an import from `site-packages`, matching package metadata, `py.typed`,
a base install without Channels, `django.setup()`, schema compilation, and a
real GraphQL query. The dependency audit receives that same prebuilt wheel and
does not rebuild it.

## Code Review Process

### What We Look For

- **Correctness**: Does the code work as intended?
- **Testing**: Are there adequate tests?
- **Documentation**: Is the code well-documented?
- **Performance**: Does it maintain good performance?
- **Style**: Does it follow our coding standards?
- **Compatibility**: Does it work with all supported versions?

### Timeline

- Initial review: Within 1-2 weeks
- Follow-up reviews: Within a few days
- Complex changes may take longer

## Getting Help

### Discord/Slack

We don't currently have a Discord or Slack, but you can:

### GitHub Discussions

Use [GitHub Discussions](https://github.com/eamigo86/django-graphex/discussions) for:
- Questions about contributing
- Feature discussions
- General help

### Issues

Use [GitHub Issues](https://github.com/eamigo86/django-graphex/issues) for:
- Bug reports
- Feature requests
- Documentation improvements

## Recognition

Contributors are recognized in several ways:

- Listed in the repository contributors
- Mentioned in release notes for significant contributions
- Can be added as maintainers for sustained contributions

## Code of Conduct

### Our Pledge

We are committed to making participation in our project a harassment-free experience for everyone, regardless of:
- Age, body size, disability, ethnicity
- Gender identity and expression
- Level of experience, education
- Nationality, personal appearance
- Race, religion, sexual identity and orientation

### Our Standards

**Positive behavior includes:**
- Using welcoming and inclusive language
- Being respectful of differing viewpoints
- Gracefully accepting constructive criticism
- Focusing on what is best for the community
- Showing empathy towards other community members

**Unacceptable behavior includes:**
- Trolling, insulting/derogatory comments, personal attacks
- Public or private harassment
- Publishing others' private information without permission
- Other conduct which could reasonably be considered inappropriate

### Enforcement

Project maintainers have the right to:
- Remove, edit, or reject comments, commits, code, wiki edits, issues
- Ban temporarily or permanently any contributor for behaviors deemed inappropriate

Report any issues to the project maintainers via GitHub issues or email.

## Thank You! 🎉

Your contributions help make django-graphex better for everyone. Whether it's:

- Fixing a typo in documentation
- Adding a new feature
- Reporting a bug
- Improving performance

Every contribution matters and is appreciated! 🙏
