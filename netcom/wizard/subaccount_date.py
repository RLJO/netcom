# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SubAccountDate(models.TransientModel):
    _name = 'sub.account.date'
    _description = 'Sub-Account Date'

    activation_date = fields.Date(string='Activation Date')
    perm_up_date = fields.Date(string='Permanent Activation Date')
    price_review_date = fields.Date(string='Price Review Date')
    
    activate = fields.Boolean(string='Activation Date', default=True)
    perm_up = fields.Boolean(string='Permanent Activation Date')
    price_review = fields.Date(string='Price Review Date')

    subaccount_id = fields.Many2one(comodel_name='sub.account', default=lambda self: self.env.context.get('active_id', None), required=True)

    def action_modify_date(self):
        if self.activate:
            self.subaccount_id.sudo().write({'activation_date': self.activation_date})
        
        if self.perm_up:
            self.subaccount_id.sudo().write({'perm_up_date': self.perm_up_date})
        
        if self.price_review:
            self.subaccount_id.sudo().write({'price_review_date': self.price_review_date})

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sub.account',
            'res_id': self.subaccount_id.id,
            'name': self.subaccount_id.display_name,
            'view_mode': 'form',
            'views': [(False, "form")],
        }
