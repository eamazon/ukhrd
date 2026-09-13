"""Readers turn a published thing into rows. One per SHAPE, not one per dataset.

A reader takes a starting URL and returns a list of dicts. It must NOT touch the database, so it can be
tested against a saved page with no network and no database.
"""
from ukhrd.readers import nhs_dd

READERS = {"nhs_dd": nhs_dd.read}
