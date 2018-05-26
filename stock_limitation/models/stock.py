# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class stock_location(models.Model):
    _inherit = 'stock.location'

    @api.depends('own_user_ids', 'location_id.own_user_ids', 'location_id.user_ids')
    def _compute_user_ids(self):
        for loc in self:
            loc.user_ids = (loc.location_id and loc.location_id.user_ids.ids or []) + loc.own_user_ids.ids

    def _inverse_own_user_ids(self):
        for loc in self:
            children_ids = self.env['stock.location'].search([('location_id', '=', loc.id)])
            for child in children_ids:
                child._compute_user_ids()
                child._inverse_own_user_ids()

    @api.multi
    def name_get(self):
        return super(stock_location, self.sudo()).name_get()

    own_user_ids = fields.Many2many(
        'res.users',
        'stock_location_users_rel',
        'slid',
        'user_id',
        'Own Accepted Users',
        inverse=_inverse_own_user_ids,
    )
    user_ids = fields.Many2many(
        'res.users',
        compute=_compute_user_ids,
        string='Accepted Users',
        store=True,
    )
