# -*- coding: utf-8 -*-

from odoo import models, fields, api

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    READONLY_STATES = {
        'purchase': [('readonly', True)],
        'done': [('readonly', True)],
        'cancel': [('readonly', True)],
    }

    @api.model
    def _default_picking_type(self):
        return False

    picking_type_id = fields.Many2one('stock.picking.type', 'Deliver To', states=READONLY_STATES, required=True, \
        default=_default_picking_type, help='This will determine operation type of incoming shipment')