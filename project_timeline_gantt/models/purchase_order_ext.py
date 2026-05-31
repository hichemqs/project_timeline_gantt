# -*- coding: utf-8 -*-
"""
purchase.order extension
========================
Thin override that hooks purchase.order lifecycle events into the
TimelineSyncService. No business logic lives here — all sync logic
is delegated to the service.
"""

from odoo import models
from ..services.timeline_sync_service import SYNC_IN_PROGRESS_KEY


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    def create(self, vals_list):
        records = super().create(vals_list)
        sync = self.env['project.timeline.sync.service']
        for record in records:
            sync.sync_record(record)
        return records

    def write(self, vals):
        # Guard: skip forward sync when this write was triggered by back-sync
        result = super().write(vals)
        if not self.env.context.get(SYNC_IN_PROGRESS_KEY):
            sync = self.env['project.timeline.sync.service']
            if sync.should_sync(self._name, vals.keys()):
                for record in self:
                    sync.sync_record(record)
        return result

    def unlink(self):
        sync = self.env['project.timeline.sync.service']
        for record in self:
            sync.desync_record(record)
        return super().unlink()
