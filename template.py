#!/usr/bin/env python3
################################################################
# Copyright (c) 2026 Witalis Domitrz <witekdomitrz@gmail.com>
# AGPL License
################################################################
#
# /// script
# dependencies = [
# ]
# ///

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import cast

from typing_extensions import Self


@dataclass(frozen=True, kw_only=True)
class Args:
    who: str

    @classmethod
    def from_args(cls, argv: list[str] | None = None) -> Self:
        parser = argparse.ArgumentParser()
        _ = parser.add_argument("--who", type=str, default="World")
        args = parser.parse_args(argv)
        return cls(who=cast(str, args.who))

    def run(self) -> int:
        print(f"Hello {self.who}!")
        return 0


if __name__ == "__main__":
    raise SystemExit(Args.from_args().run())
