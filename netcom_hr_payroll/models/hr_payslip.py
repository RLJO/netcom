#-*- coding:utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, models, fields


class HRPayslip(models.Model):
    _inherit = 'hr.payslip'

    def get_total(self, code):
        return self.env['hr.payslip.line'].search([('slip_id','=',self.id),('code','=',code)], limit=1).total
