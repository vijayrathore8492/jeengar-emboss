# Contributing

Thanks for looking. Ground rules, short:

- **Issues** are open: bugs, ideas, questions, photos of burns that went wrong. Use the templates.
- **Fixes are done by the maintainers.** If you want to send code anyway, open a pull request
  from a fork; `main` is protected and every PR needs a maintainer review before it can merge.
  Small, single-purpose PRs get looked at; large rewrites usually don't.
- Anything touching `emboss/gcode.py`, `emboss/grbl.py` or power scaling must say what
  machine and leather it was tested on. Numbers there burn things.
- No new dependencies without a reason in the PR.
- Fonts: only OFL / open-licensed files can be added to `assets/fonts`. Anything else belongs
  in the user's *My fonts* folder, never in the repo.
- By contributing you agree your code is released under the repo's MIT licence.
