# -*- coding: utf-8 -*-
"""
project.timeline
================
Consolidated timeline model. Acts as the single table queried by the Gantt
view. Records are kept in sync with their source models through
TimelineSyncService.

Bidirectional sync: when date_start / date_end are modified directly on
this model (e.g. via Gantt drag & drop), the changes are propagated back
to the originating source record via TimelineSyncService.back_sync_to_source().
"""

from odoo import api, fields, models
from ..services.timeline_sync_service import SYNC_IN_PROGRESS_KEY


class ProjectTimeline(models.Model):
    _name = 'project.timeline'
    _description = 'Project Timeline'
    _order = 'date_start asc, name asc'

    # ------------------------------------------------------------------
    # Core fields
    # ------------------------------------------------------------------

    name = fields.Char(
        string='Name',
        required=True,
        index=True,
    )

    timeline_type = fields.Selection(
        selection=[
            ('purchase', 'Purchase Order'),
            ('sale', 'Sales Order'),
            ('manufacturing', 'Manufacturing Order'),
        ],
        string='Type',
        required=True,
        index=True,
    )

    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Project',
        index=True,
        ondelete='set null',
    )

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer / Partner',
        index=True,
        ondelete='set null',
    )

    supplier_id = fields.Many2one(
        comodel_name='res.partner',
        string='Supplier',
        index=True,
        ondelete='set null',
    )

    date_start = fields.Datetime(
        string='Start Date',
        index=True,
    )

    date_end = fields.Datetime(
        string='End Date',
        index=True,
    )

    # ------------------------------------------------------------------
    # Source reference (soft foreign key — model-agnostic)
    # ------------------------------------------------------------------

    source_model = fields.Char(
        string='Source Model',
        readonly=True,
        index=True,
    )

    source_record_id = fields.Integer(
        string='Source Record ID',
        readonly=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # Display / UI fields
    # ------------------------------------------------------------------

    display_color = fields.Integer(
        string='Color Index',
        default=0,
    )

    active = fields.Boolean(
        string='Active',
        default=True,
    )

    # ------------------------------------------------------------------
    # Computed: link to open the source record form
    # ------------------------------------------------------------------

    source_url = fields.Char(
        string='Source URL',
        compute='_compute_source_url',
    )

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------

    def write(self, vals):
        """
        Intercept date changes to propagate them back to the source record
        (bidirectional sync / Gantt drag & drop support).

        The SYNC_IN_PROGRESS_KEY context flag prevents the subsequent
        source-model write() from re-triggering a forward sync, avoiding
        infinite recursion.
        """
        result = super().write(vals)

        # Only back-sync when the write did NOT originate from a forward sync
        if not self.env.context.get(SYNC_IN_PROGRESS_KEY):
            date_fields = {'date_start', 'date_end'}
            if date_fields & set(vals.keys()):
                sync_service = self.env['project.timeline.sync.service']
                for record in self:
                    sync_service.back_sync_to_source(record, vals)

        return result

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_open_source_record(self):
        """
        Return a window action that opens the originating business document.
        Called when the user clicks a Gantt block (via the open_record button
        or a JS override in the Gantt renderer).
        """
        self.ensure_one()
        if not self.source_model or not self.source_record_id:
            return False

        # Resolve the ir.model to get a human-readable name
        IrModel = self.env['ir.model']
        model_rec = IrModel.search(
            [('model', '=', self.source_model)], limit=1
        )

        return {
            'type': 'ir.actions.act_window',
            'name': model_rec.name if model_rec else self.source_model,
            'res_model': self.source_model,
            'res_id': self.source_record_id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------

    @api.depends('source_model', 'source_record_id')
    def _compute_source_url(self):
        """Build a relative URL for the source record (informational)."""
        base = self.env['ir.config_parameter'].sudo().get_param(
            'web.base.url', ''
        )
        for rec in self:
            if rec.source_model and rec.source_record_id:
                rec.source_url = (
                    f"{base}/odoo/{rec.source_model.replace('.', '-')}"
                    f"/{rec.source_record_id}"
                )
            else:
                rec.source_url = False
