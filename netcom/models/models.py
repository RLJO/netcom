# -*- coding: utf-8 -*-

from odoo import models, fields, api

class Partner(models.Model):
    _name = 'res.partner'
    _inherit = 'res.partner'
 
    parent_account_number = fields.Char('Parent Account Number', required=True)
    
    @api.multi
    def name_get(self):
        res = []

        for partner in self:
            result = partner.name
            if partner.parent_account_number:
                result = str(partner.name) + " " + str(partner.parent_account_number)
                print(str(partner.name))
                print(str(partner.parent_account_number))
            res.append((partner.id, result))
        return res

    
    
    
    
    
#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
# 
#     @api.depends('value')
#     def _value_pc(self):
#         self.value2 = float(self.value) / 100