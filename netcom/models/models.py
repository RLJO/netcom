# -*- coding: utf-8 -*-

from odoo import models, fields, api

class Partner(models.Model):
    _name = 'res.partner'
    _inherit = 'res.partner'
 
    parent_account_number = fields.Char('Parent Account Number')
    
    @api.multi
    def name_get(self):
        res = []

        for partner in self:
            result = partner.name
            if partner.parent_account_number:
                result = str(partner.name) + " " + str(partner.parent_account_number)
            res.append((partner.id, result))
        return res

class Lead(models.Model):
    _name = "crm.lead"
    _inherit = 'crm.lead'
    
    nrc = fields.Float('NRC', track_visibility='onchange')
    mrc = fields.Float('MRC', track_visibility='onchange')
    
class EquipmentType(models.Model):
    _name = "equipment.type"
    _description = "Equipment Types"
    _order = "name"
    _inherit = ['mail.thread']
    
    name = fields.Char('Name', required=True, track_visibility='onchange')
    code = fields.Char('Code', required=True, track_visibility='onchange')
    active = fields.Boolean('Active', )
    
class BrandType(models.Model):
    _name = "brand.type"
    _description = "Brand Types"
    _order = "name"
    _inherit = ['mail.thread']
    
    name = fields.Char('Name', required=True, track_visibility='onchange')
    code = fields.Char('Code', required=True, track_visibility='onchange')
    active = fields.Boolean('Active', )
    
class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    brand = fields.Many2one('brand.type', string='Brand', track_visibility='onchange', index=True)
    equipment_type = fields.Many2one('equipment.type', string='Equipment Type', track_visibility='onchange', index=True)
    desc = fields.Text('Remarks/Description')
    
    
#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
# 
#     @api.depends('value')
#     def _value_pc(self):
#         self.value2 = float(self.value) / 100