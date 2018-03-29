# -*- coding: utf-8 -*-

from odoo import models, fields, api



class Picking(models.Model):
    _name = "stock.picking"
    _inherit = 'stock.picking'
    
    def _default_owner(self):
        return self.env.context.get('default_employee_id') or self.env['res.users'].browse(self.env.uid).partner_id
    
    owner_id = fields.Many2one('res.partner', 'Owner',
        states={'done': [('readonly', True)], 'cancel': [('readonly', True)]}, default=_default_owner,
        help="Default Owner")
    


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ['sale.order']
    _description = "Quotation"
    
    remarks = fields.Char('Remarks', track_visibility='onchange')
    period = fields.Integer('Service Contract Period (in months)', default="1", required=True, track_visibility='onchange')
    
class SaleOrderLine(models.Model):
    _name = 'sale.order.line'
    _description = 'Sales Order Line'
    _inherit = ['sale.order.line']
    
    type = fields.Selection([('sale', 'Sale'), ('lease', 'Lease')], string='Type', required=True,default='sale')
    nrc_mrc = fields.Char('MRC/NRC', compute='_compute_mrc_nrc', readonly=True, store=True)
    sub_account_id = fields.Many2one('sub.account', string='Child Account', index=True, ondelete='cascade')
    
    @api.one
    @api.depends('product_id')
    def _compute_mrc_nrc(self):
        if self.product_id.recurring_invoice == True:
            self.nrc_mrc = "MRC"
        else:
            self.nrc_mrc = "NRC"
             
    @api.multi
    @api.onchange('type')
    def type_change(self):
        self.product_id = False

            
    @api.multi
    @api.onchange('product_id')
    def product_id_change(self):
        if not self.product_id:
            return {'domain': {'product_uom': []}}

        vals = {}
        domain = {'product_uom': [('category_id', '=', self.product_id.uom_id.category_id.id)]}
        if not self.product_uom or (self.product_id.uom_id.id != self.product_uom.id):
            vals['product_uom'] = self.product_id.uom_id
            vals['product_uom_qty'] = 1.0

        product = self.product_id.with_context(
            lang=self.order_id.partner_id.lang,
            partner=self.order_id.partner_id.id,
            quantity=vals.get('product_uom_qty') or self.product_uom_qty,
            date=self.order_id.date_order,
            pricelist=self.order_id.pricelist_id.id,
            uom=self.product_uom.id
        )

        result = {'domain': domain}

        title = False
        message = False
        warning = {}
        if product.sale_line_warn != 'no-message':
            title = _("Warning for %s") % product.name
            message = product.sale_line_warn_msg
            warning['title'] = title
            warning['message'] = message
            result = {'warning': warning}
            if product.sale_line_warn == 'block':
                self.product_id = False
                return result

        name = product.name_get()[0][1]
        if product.description_sale:
            name += '\n' + product.description_sale
        vals['name'] = name

        self._compute_tax_id()

        if self.order_id.pricelist_id and self.order_id.partner_id:
            vals['price_unit'] = self.env['account.tax']._fix_tax_included_price_company(self._get_display_price(product), product.taxes_id, self.tax_id, self.company_id)
        if self.type == "lease":
            vals['price_unit'] = self.product_id.lease_price
        self.update(vals)

        return result


