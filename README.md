# research-checks

Shared checks for the research repositories behind
[jacobbuildmodel.github.io](https://jacobbuildmodel.github.io): every prediction
there is sealed (its THESIS.md and scripts fixed by md5) before the data is
opened, then scored in public. These checks run on every commit, on GitHub's
free runners, so any reader can see from the Actions tab whether a seal still
holds and whether the published outputs still reproduce.

No AI runs inside these checks, and they use no secrets.

The reusable workflows arrive in pull request #1. Until it is merged this
repository holds only this README and the licence.

Licence: MIT (see LICENSE).
