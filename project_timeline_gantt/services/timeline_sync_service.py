# -*- coding: utf-8 -*-
"""
TimelineSyncService
===================
Central service responsible for all synchronization between source business
models and the consolidated project.timeline model.

Design goals:
- Declarative field mapping (TIMELINE_SOURCE_MAP) — adding a new source model
  requires only a new entry in that dict and a thin model override.
- No direct coupling between source models: each model calls
  TimelineSyncService.sync_record() / desync_record().
- Re-entrancy guard via context key prevents bidirectional recursion.
"""

import logging
from odoo import api, models

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-entrancy guard key injected into env.context during back-sync writes
# ---------------------------------------------------------------------------
SYNC_IN_PROGRESS_KEY = '_timeline_sync_in_progress'


# ---------------------------------------------------------------------------
# Declarative source map
# ---------------------------------------------------------------------------
# Structure per entry:
#   'source_model_name': {
#       'timeline_type':  <selection key on project.timeline>,
#       'name':           callable(record) -> str,
#       'date_start':     field name on source model for start,
#       'date_end':       field name on source model for end,
#       'project_field':  field name yielding project.project (or None),
#       'partner_field':  field name yielding res.partner (or None),
#       'supplier_field': field name yielding res.partner (or None),
#       'color':          integer color index,
#       # Fields that, when written, should trigger a re-sync
#       'watch_fields':   set of field names,
#   }
#
# NOTE on Sales Order date_start choice (Odoo 19):
#   sale.order does not expose a native "start" date. The most semantically
#   correct field is `date_order` (the confirmation date / order date), which
#   marks the beginning of the fulfilment obligation. `commitment_date` is
#   used as date_end because it represents the promised delivery deadline.
#   If `commitment_date` is not set, `date_deadline` is used as fallback.
#   This is documented here to satisfy the specification's requirement for
#   an explicit decision record.
# ---------------------------------------------------------------------------
TIMELINE_SOURCE_MAP = {
    'purchase.order': {
        'timeline_type': 'purchase',
        'name': lambda r: f"{r.name} - {r.partner_id.name}" if r.partner_id else r.name,
        'date_start': 'date_approve',       # date_approved in Odoo 19 API
        'date_end': 'date_planned',
        'project_field': None,
        'partner_field': 'partner_id',
        'supplier_field': 'partner_id',
        'color': 1,
        'watch_fields': {'date_approve', 'date_planned', 'partner_id', 'name', 'state'},
    },
    'sale.order': {
        'timeline_type': 'sale',
        'name': lambda r: f"{r.name} - {r.partner_id.name}" if r.partner_id else r.name,
        'date_start': 'date_order',         # confirmation / order date — see note above
        'date_end': 'commitment_date',      # promised delivery; falls back to date_deadline
        'date_end_fallback': 'date_deadline',
        'project_field': None,
        'partner_field': 'partner_id',
        'supplier_field': None,
        'color': 2,
        'watch_fields': {
            'date_order', 'commitment_date', 'date_deadline',
            'partner_id', 'name', 'state',
        },
    },
    'mrp.production': {
        'timeline_type': 'manufacturing',
        'name': lambda r: (
            f"{r.name} - {r.sale_id.partner_id.name}"
            if hasattr(r, 'sale_id') and r.sale_id and r.sale_id.partner_id
            else (
                f"{r.name} - {r.project_id.name}"
                if hasattr(r, 'project_id') and r.project_id
                else r.name
            )
        ),
        'date_start': 'date_start',
        'date_end': 'date_deadline',
        'project_field': 'project_id' ,     # present only if mrp_project bridge installed
        'partner_field': None,
        'supplier_field': None,
        'color': 3,
        'watch_fields': {'date_start', 'date_deadline', 'name', 'state'},
    },
}

# Reverse map: timeline_type -> source_model string (for back-sync)
TIMELINE_TYPE_TO_MODEL = {
    cfg['timeline_type']: model
    for model, cfg in TIMELINE_SOURCE_MAP.items()
}

# Reverse field map for back-sync: timeline_type -> {timeline_field: source_field}
BACK_SYNC_FIELD_MAP = {
    'purchase': {
        'date_start': 'date_approve',
        'date_end': 'date_planned',
    },
    'sale': {
        'date_start': 'date_order',
        'date_end': 'commitment_date',
    },
    'manufacturing': {
        'date_start': 'date_start',
        'date_end': 'date_deadline',
    },
}


class TimelineSyncService(models.AbstractModel):
    """
    Abstract model used as a service singleton accessible via self.env.
    All methods are instance methods so they participate in the ORM
    transaction context (env, cursor, user).
    """
    _name = 'project.timeline.sync.service'
    _description = 'Project Timeline Synchronization Service'

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync_record(self, record):
        """
        Create or update the project.timeline entry for *record*.

        :param record: a single-record ORM recordset from a supported model.
        """
        model_name = record._name
        cfg = TIMELINE_SOURCE_MAP.get(model_name)
        if not cfg:
            _logger.warning(
                'TimelineSyncService.sync_record called with unsupported model %s',
                model_name,
            )
            return

        vals = self._build_timeline_vals(record, cfg)
        Timeline = self.env['project.timeline']
        existing = Timeline.search([
            ('source_model', '=', model_name),
            ('source_record_id', '=', record.id),
        ], limit=1)

        if existing:
            # Write without triggering back-sync
            existing.with_context(**{SYNC_IN_PROGRESS_KEY: True}).write(vals)
            _logger.debug('Timeline updated for %s id=%s', model_name, record.id)
        else:
            Timeline.with_context(**{SYNC_IN_PROGRESS_KEY: True}).create(vals)
            _logger.debug('Timeline created for %s id=%s', model_name, record.id)

    def desync_record(self, record):
        """
        Archive (soft-delete) the project.timeline entry for *record*.

        :param record: a single-record ORM recordset from a supported model.
        """
        model_name = record._name
        timeline = self.env['project.timeline'].search([
            ('source_model', '=', model_name),
            ('source_record_id', '=', record.id),
        ], limit=1)
        if timeline:
            timeline.with_context(**{SYNC_IN_PROGRESS_KEY: True}).write({'active': False})
            _logger.debug('Timeline archived for %s id=%s', model_name, record.id)

    def back_sync_to_source(self, timeline_record, changed_vals):
        """
        Propagate date changes from project.timeline back to the source record.
        Called from project.timeline.write() when date_start / date_end change.

        :param timeline_record: single project.timeline record.
        :param changed_vals: dict of values being written to the timeline.
        """
        field_map = BACK_SYNC_FIELD_MAP.get(timeline_record.timeline_type)
        if not field_map:
            return

        source_model = TIMELINE_TYPE_TO_MODEL.get(timeline_record.timeline_type)
        if not source_model or not timeline_record.source_record_id:
            return

        source_vals = {}
        for tl_field, src_field in field_map.items():
            if tl_field in changed_vals:
                source_vals[src_field] = changed_vals[tl_field]

        if not source_vals:
            return

        try:
            source_record = self.env[source_model].browse(
                timeline_record.source_record_id
            )
            if source_record.exists():
                source_record.with_context(**{SYNC_IN_PROGRESS_KEY: True}).write(
                    source_vals
                )
                _logger.debug(
                    'Back-sync wrote %s to %s id=%s',
                    source_vals, source_model, timeline_record.source_record_id,
                )
        except Exception as exc:
            # Back-sync is best-effort; never break the timeline save
            _logger.error(
                'Back-sync failed for %s id=%s: %s',
                source_model, timeline_record.source_record_id, exc,
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_timeline_vals(self, record, cfg):
        """Build the vals dict to create/write a project.timeline record."""
        # Resolve dates
        date_start = getattr(record, cfg['date_start'], None) or False
        date_end_field = cfg.get('date_end')
        date_end = getattr(record, date_end_field, None) if date_end_field else False
        # Fallback for sale.order when commitment_date is empty
        if not date_end and cfg.get('date_end_fallback'):
            date_end = getattr(record, cfg['date_end_fallback'], None) or False

        # Resolve relational fields safely
        partner_field = cfg.get('partner_field')
        partner = getattr(record, partner_field, False) if partner_field else False
        partner_id = partner.id if partner else False

        supplier_field = cfg.get('supplier_field')
        supplier = getattr(record, supplier_field, False) if supplier_field else False
        supplier_id = supplier.id if supplier else False

        project_field = cfg.get('project_field')
        project = getattr(record, project_field, False) if project_field else False
        project_id = project.id if project else False

        return {
            'name': cfg['name'](record),
            'timeline_type': cfg['timeline_type'],
            'date_start': date_start,
            'date_end': date_end,
            'source_model': record._name,
            'source_record_id': record.id,
            'partner_id': partner_id,
            'supplier_id': supplier_id,
            'project_id': project_id,
            'display_color': cfg.get('color', 0),
            'active': True,
        }

    def should_sync(self, model_name, changed_fields):
        """
        Return True if any of *changed_fields* are in the watch list
        for *model_name*. Used by write() overrides to skip no-op syncs.
        """
        cfg = TIMELINE_SOURCE_MAP.get(model_name)
        if not cfg:
            return False
        return bool(set(changed_fields) & cfg.get('watch_fields', set()))
