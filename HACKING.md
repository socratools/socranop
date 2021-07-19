Notes for those wanting to help out
===================================

First of all, thank you!  I appreciate all feedback, pull requests, and gentle criticism!

Development Environment
-----------------------

To ensure homogeneity of development environments, I recommend using
`pipenv` and python 3.8 (though python 3.6 is the minimum supported
version).  `pipenv` can be installed via `pip` in the usual ways.


### Get a git clone of the source repository

    [user@host ~]$ git clone https://github.com/socratools/socranop.git
    [user@host ~]$ cd socranop
    [user@host socranop]$ _


### Set up and use pipenv

`pipenv install --dev`
- Sets up an appropriate virtual environment, installs all appropriate
  development packages, and egg-links to our source directory so that
  the virtualenv will actually use the source files from this source
  directory.

  If you are getting the black version subdependency problem on Debian
  or Ubuntu, `pipenv lock --pre --clear` might help.

`tools/link_system_libs`
- Set up a symlink to your system's 'gi' lib which isn't otherwise available
  via pip (allows you to run the D-Bus service and the gui from within pipenv)

`pipenv shell`
- Starts a subshell with the appropriate environment so that the
  sandboxed libraries and utilities are in use

FIXME05: You can start the D-Bus service by running
         `socranop-session-service` from a pipenv. Bus activation
         only works per-user, though, not per-pipenv, as the session
         bus only looks for `*.service` files in one specific location
         in $HOME.

### Set up pre-commit

`pre-commit install` (inside of pipenv shell)
- Set up git hooks management so every commit gets checked/fixed
- Only needs to be done once after cloning the `socranop` repo

### Adding new dependencies

`pipenv install [--dev] <pgkname>`
- Installs the dependency to the local pipenv environment.  Use
  `--dev` for development-only packages, omit for run-time
  dependencies.

`pipenv-setup sync --pipfile`
- Syncs any run-time dependencies from `pipenv` to `setup.py`.

  The `socranop` pre-commit hooks run this automatically.

### Changing setup.py, setup.cfg, etc.

After changing any of the setup config files, it is advisable to run

```sh
python3 setup.py clean --all
```

before the next

```sh
python3 setup.py bdist_wheel
```

packaging test.

### Things to avoid in code

For compatibility with all versions of Python >= 3.6, avoid the
following:

  * The `missing_ok` parameter to several `pathlib.Path` methods
    (since Python 3.8)

  * The `@functools.cached_property` decorator (since Python 3.8)

  * `importlib.metadata.version()` (`importlib.metadata` since
    Python 3.8)


Submitting Changes
------------------

- Please ensure that `pytest` passes, using `pytest` itself or `tox`.

  Github runs this for you on all branches as well, and I'm working on
  getting the feedback from that integrated into the pull requests,
  eventually.

  Try to test new code thoroughly.  I'm working on increasing code
  coverage as I go as well.  Use `pytest` or `tox` to test.

  The `pre-commit` hooks ensure `pytest` is passing on every commit, too.

- Run `flake8` and `black` to format your code.

  The `socranop` source code is written to conform to stock `flake8`
  without any extra plugins installed.  Using `pipenv` (see above)
  should make sure you have the right set of `flake8` plugins
  installed.

  The `pre-commit` hooks will do this for you automatically.

- If your Python code adds or touches a very short line which is also
  in other places in the same source file (e.g. `try:`, `pass`,
  `next`, or `continue`), please try adding a useful comment to the
  line which makes the line unique enough that git's diff generator
  cannot confuse this instance of the line with a completely different
  instance from another part of the code.

- Add yourself to the [`CONTRIBUTORS.md`](CONTRIBUTORS.html) file if you
  want, but if you do, please also run `tools/contrib_to_about` to
  synchronize the changes in there to the GUI about screen.

  The `pre-commit` hooks will update the GUI about screen for you
  automatically.

- If you have been git rebasing and had to fix a lot of conflicts, it
  is possible that a source tree which does not pass the `pre-commit`
  checks has been committed anyway.

  You can make sure that all the commits in your `my-local-branch`
  branch after `main` pass the pre-commit checks by running

      $ git rebase --exec 'pre-commit run -a' -i main my-local-branch

  which will then stop at whatever commit that failed the `pre-commit`
  run. Then you can fix it until `pre-commit run -a` succeeds, amend
  the commit and `git rebase --continue`. Repeat fixing, amending, and
  continuing until the interactive rebase has completed successfully.

- Open pull requests to the default branch, currently named `main`.

- Version numbers are semver-like, and reflect more about the D-Bus protocol
  compatibility than anything else:

    - A build bump (0.3.5 -> 0.3.6) is a feature bump.  It can add new things
      to the D-Bus interface, but not remove or fundamentally alter existing
      datastructures.

    - A minor bump (0.3.x -> 0.4.0) implies a D-Bus incompatibility boundary.
      This may include changes to pre-existing D-Bus data structures or remove
      D-Bus endpoints.

    - A major bump (0.x.y -> 1.0.0) hasn't happened yet.  Maybe it will some day :)

- The official release schedule is sporadic and ad-hoc (aka when I feel like
  it).  If you think there's enough in mainline that you want me to kick a
  release, just send me an email or open an issue.


Interfaces, Namespaces, Specifications
======================================

This lists and links to (at least some) interfaces, namespaces, and
specifications which `socranop` comes into contact with.

  * [D-Bus](https://dbus.freedesktop.org/doc/dbus-specification.html)

  * [Desktop Entry Specification](https://specifications.freedesktop.org/desktop-entry-spec/desktop-entry-spec-latest.html)

    The `.desktop` file hooks the `socranop-gui` GUI application
    into the desktop environment's list of applications.

  * [Desktop Menu Specification](https://specifications.freedesktop.org/menu-spec/menu-spec-1.0.html)

    Defines e.g. the `Categories=` part of the `.desktop` file.

  * [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html)

    This specifies the locations the socranop Desktop file and
    icons should be installed to.
