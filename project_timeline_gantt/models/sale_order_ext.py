# -*- coding: utf-8 -*-
"""
sale.order extension
====================
Thin override that hooks sale.order lifecycle events into the
TimelineSyncService.

Date field decision (documented per specification):
- date_start  -> sale.order.date_order  (the confirmation/order date; marks
                  the beginning of the fulfilment obligation)
- date_end    -> sale.order.commitment_date (the promised delivery deadline)
                  Fallback: date_deadline (generic deadline field)

Rationale: `products_availability` on sale.order in Odoo 19 is a computed
Selection field reflecting stock availability status — it is NOT a date field
and therefore unsuitable as a timeline date. `date_order` is the semantically
correct "start" of a sales order's lifecycle on the Gantt.
"""

from odoo import models
from ..services.timeline_sync_service import SYNC_IN_PROGRESS_KEY


class SaleOrder(models.Model):
    _inherit = 'sale.order'

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
