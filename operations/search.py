"""Shared, reusable search for Operations list pages.

One ``apply_search`` helper gives every list the same behaviour so we never grow a
second, inconsistent implementation:

* case-insensitive partial matching (``icontains``);
* multiple words are AND-ed together, and each word is OR-ed across the page's chosen
  fields — so "black filament" matches an order whose supplier/description/material
  between them contain both words, even in different fields;
* fields may use ``__`` to span related tables;
* each row is returned once (``distinct``), even when a field spans a to-many relation.

The caller is responsible for permission scoping (every Operations view is
``@admin_required``); this only narrows an already-authorized queryset.
"""
from django.db.models import Q

# Cap how many words become SQL clauses, so a pathological paste can't build a huge query.
MAX_TERMS = 10


def search_terms(query):
    """The query split into at most ``MAX_TERMS`` lowercase words (for Python-side
    match highlighting). Returns an empty list for a blank query."""
    return [t for t in (query or '').lower().split()][:MAX_TERMS]


def apply_search(queryset, query, fields):
    """Narrow ``queryset`` by ``query`` across ``fields``.

    Returns the queryset unchanged when the query is blank or no fields are given.
    """
    query = (query or '').strip()
    if not query or not fields:
        return queryset
    for term in query.split()[:MAX_TERMS]:
        clause = Q()
        for field in fields:
            clause |= Q(**{'%s__icontains' % field: term})
        queryset = queryset.filter(clause)
    return queryset.distinct()
