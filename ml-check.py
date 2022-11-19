#!/usr/bin/env python3
"""
This tool is used for checking the public kernel-team mailing list for patches that
have not been sufficiently reviewed. A best-effort attempt is made at characterizing
emails based on their subject line. For this reason, false positives and negatives 
will happen.

The basic idea is that we download and cache each year.month txt.gz log from the 
server. After the first run, only the txt.gz for the current year.month will be 
downloaded. All historical messages are stored in what we called a stable mailbox. 
This saves us from parsing them over and over again. The current month's mail is 
downloaded and parsed everytime this tool is run. This could be done better to save
some time.

Message threading depends on the Message-ID, In-Reply-To, and References headers.
With these three headers, we can sufficiently thread most messages.

By default, we look at the last 21 weeks of patches. Since a patch always preceeds 
a response, we should never see a false positive due to this caching window.

The monthly txt.gz file is not generated immediately for each message. This means 
that if you run this tool, review a patch, then re-run this tool you probably will 
not see any change in the results. Try again later because I'm not sure exactly when 
the file is generated.
"""

import argparse
import logging
import os
import shutil
import sys
from datetime import datetime, timezone

from ml_check.kteam_mbox import CustomPatchFilter, KTeamMbox, ReplyTypes
from ml_check.logging import logger


def save_patch_set(out_directory, patch_set):
    """Write a patch set to disk as a patch files
    :param out_directory: str write results to this directory
    :param patch_set: PatchSet
    """
    patch_dir = os.path.join(out_directory, patch_set.epoch_patch.generate_patch_name())
    os.mkdir(patch_dir)

    for patch in patch_set.patches:
        patch_file = os.path.join(patch_dir, f"{patch.generate_patch_name()}.patch")
        with open(patch_file, "w") as f:
            f.write(patch.generate_patch())

    # Generate a summary text file showing reply stats
    age_days = (datetime.now(timezone.utc) - patch_set.epoch_patch.timestamp).days
    patch_count = len(patch_set.patches)
    ack_count = len(patch_set.acks)
    nak_count = len(patch_set.naks)
    applied_count = len(patch_set.applieds)

    summary_file = os.path.join(patch_dir, "summary.txt")
    with open(summary_file, "w") as f:
        f.write(f"{patch_set.epoch_patch.subject}\n")
        f.write(f"age: {age_days} days\n")
        f.write(f"size: {patch_count} patches\n")
        f.write(f"acks: {ack_count}\n")
        f.write(f"naks: {nak_count}\n")
        f.write(f"applied: {applied_count > 0}\n")


def main(weeks_back, patch_output, reply_type, reply_count, clear_cache):
    """Run mailing list checker
    :param weeks_back: int how many weeks back from today to scan
    :param reply_type: str which types of replies to dump
    :param reply_count: int if reply_type == "ack" dump patches with this many of that type
    :param patch_output: str if specified, emit .patches to this directory
    :param clear_cache: bool delete local cache (will force download all new mail)
    """
    kteam = KTeamMbox()
    kteam.fetch_mail(weeks_back, clear_cache)

    if patch_output:
        # Ensure patch output directory exists and is clean
        patch_output = os.path.expanduser(patch_output)
        if os.path.exists(patch_output):
            shutil.rmtree(patch_output)
        os.mkdir(patch_output)

    patch_filter = CustomPatchFilter(reply_type, reply_count)

    # Prints from oldest to newest
    patch_sets = kteam.filter_patches(patch_filter.apply)
    for patch_set in sorted(patch_sets):
        if patch_output:
            save_patch_set(patch_output, patch_set)

    return 0


if __name__ == "__main__":
    app_description = """Kernel Team mailing-list checker"""
    app_epilog = (
        """Checks for patches requiring review on the public kernel mailing list"""
    )
    parser = argparse.ArgumentParser(
        description=app_description,
        epilog=app_epilog,
    )
    parser.add_argument(
        "-w", "--weeks-back", default=12, type=int, help="How many weeks back to search"
    )
    parser.add_argument(
        "--clear-cache", action="store_true", help="Clear local ml-check cache"
    )
    parser.add_argument(
        "-p",
        "--patch-output",
        help="Dump patches to a file named $COVER_LETTER_SUBJECT/$PATCH_SUBJECT.patch in this directory"
        + "Any patch existing in this location will be deleted.",
    )
    parser.add_argument(
        "--all", action="store_true", help="Dump all patches regardless of review state"
    )
    parser.add_argument(
        "--naks",
        action="store_true",
        help="Dump all patches that have at least one nak",
    )
    parser.add_argument(
        "--applied", action="store_true", help="Dump all patches that have been applied"
    )
    parser.add_argument(
        "--acks", type=int, default=None, help="Dump patches with this many ACKs"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Print more debug information"
    )
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    logger.debug(args)

    reply_type = ReplyTypes.Default
    reply_count = None
    if args.all:
        reply_type = ReplyTypes.All
    elif args.acks is not None:
        reply_type = ReplyTypes.Ack
        reply_count = args.acks
    elif args.naks:
        reply_type = ReplyTypes.Nak
    elif args.applied:
        reply_type = ReplyTypes.Applied

    ret = 1
    try:
        ret = main(
            args.weeks_back,
            args.patch_output,
            reply_type,
            reply_count,
            args.clear_cache,
        )
    except BaseException as ex:
        logger.exception(ex)
    sys.exit(ret)
