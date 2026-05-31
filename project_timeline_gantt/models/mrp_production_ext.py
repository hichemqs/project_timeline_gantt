# -*- coding: utf-8 -*-
"""
mrp.production extension
=========================
Thin override that hooks mrp.production lifecycle events into the
TimelineSyncService.
"""

from odoo import models
from ..services.timeline_sync_service import SYNC_IN_PROGRESS_KEY


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

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
