# -*- coding: utf-8 -*-

from odoo import models, fields, api, _


class res_users(models.Model):
    _inherit = 'res.users'

    def _inverse_location_ids(self):
        for user in self:
            for loc in user.location_ids:
                loc._compute_user_ids()

    location_ids = fields.Many2many(
        'stock.location',
        'stock_location_users_rel',
        'user_id',
        'slid',
        'Accepted Location',
        inverse=_inverse_location_ids,
    )
