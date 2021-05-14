# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

#
# Please note that these reports are not multi-currency !!!
#

from odoo import api, fields, models, tools


class NRCPurchaseReport(models.Model):
    _name = "nrc.purchase.report"

    _description = "Purchases Orders"
    _auto = False
    _order = 'date_order desc, price_total desc'

    date_order = fields.Datetime('Order Approval Date', readonly=True, help="Date on which this document has been created", oldname='date')
    state = fields.Selection([
        ('draft', 'Draft RFQ'),
        ('sent', 'RFQ Sent'),
        ('to approve', 'To Approve'),
        ('purchase', 'Purchase Order'),
        ('done', 'Done'),
        ('cancel', 'Cancelled')
        ], 'Order Status', readonly=True)
    product_id = fields.Many2one('product.product', 'Product', readonly=True)
    product_uom = fields.Many2one('product.uom', 'Reference Unit of Measure', required=True)
    weight = fields.Float('Gross Weight', readonly=True)
    volume = fields.Float('Volume', readonly=True)

    unit_quantity = fields.Float('Product Quantity', readonly=True, oldname='quantity')
    partner_id = fields.Many2one('res.partner', 'Vendor', readonly=True)
    price_total = fields.Float('Total Price', readonly=True)
    company_id = fields.Many2one('res.company', 'Company', readonly=True)
    currency_id = fields.Many2one('res.currency', 'Currency', readonly=True)
    account_id = fields.Many2one('account.account', string='Account',  readonly=True)
    sale_order_id = fields.Many2one('sale.order','Sales Order Number', readonly=True)
    sar_ticket_number = fields.Char(string='SAR Ticket number', readonly=True)
    sub_account_id = fields.Many2one('sub.account', string='Sub Account', readonly=True)
    client_id = fields.Many2one('res.partner','Client', readonly=True)

    @api.model_cr
    def init(self):
        tools.drop_view_if_exists(self._cr, 'nrc_purchase_report')
        self._cr.execute("""
            create view nrc_purchase_report as (
                WITH currency_rate as (%s)
                select
                    min(l.id) as id,
                    s.date_order as date_order,
                    s.state,
                    s.partner_id as partner_id,
                    s.company_id as company_id,
                    s.currency_id,
                    l.product_id,
                    l.account_id,
                    s.sale_order_id,
                    s.sar_ticket_number,
                    s.sub_account_id,
                    s.client_id,
                    sum(l.price_unit / COALESCE(NULLIF(cr.rate, 0), 1.0) * l.product_qty)::decimal(16,2) as price_total,
                from purchase_order_line l
                    join purchase_order s on (l.order_id=s.id)
                    join res_partner partner on s.partner_id = partner.id
                        left join product_product p on (l.product_id=p.id)
                            LEFT JOIN ir_property ip ON (ip.name='standard_price' AND ip.res_id=CONCAT('product.product,',p.id) AND ip.company_id=s.company_id)
                    left join product_uom u on (u.id=l.product_uom)
                    left join currency_rate cr on (cr.currency_id = s.currency_id and
                        cr.company_id = s.company_id and
                        cr.date_start <= coalesce(s.date_order, now()) and
                        (cr.date_end is null or cr.date_end > coalesce(s.date_order, now())))
                group by
                    s.company_id,
                    s.partner_id,
                    u.factor,
                    s.currency_id,
                    s.sale_order_id,
                    s.sar_ticket_number,
                    s.sub_account_id,
                    s.client_id,
                    l.price_unit,
                    l.account_id,
                    l.product_uom,
                    s.dest_address_id,
                    l.product_id,
                    t.categ_id,
                    s.date_order,
                    s.state,
                    u.uom_type,
                    u.id
            )
        """ % self.env['res.currency']._select_companies_rates())