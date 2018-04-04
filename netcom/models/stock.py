# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError
from odoo.tools import float_is_zero



class HrExpenseSheetRegisterPaymentWizard(models.TransientModel):
    _name = "hr.expense.sheet.register.payment.wizard"
    _inherit = 'hr.expense.sheet.register.payment.wizard'
    
    @api.model
    def _default_partner_id(self):
        context = dict(self._context or {})
        active_ids = context.get('active_ids', [])
        expense_sheet = self.env['hr.expense.sheet'].browse(active_ids)
        if expense_sheet.payment_mode == 'company_account':
            return expense_sheet.vendor_id.id
        else:
            return expense_sheet.address_id.id or expense_sheet.employee_id.id and expense_sheet.employee_id.address_home_id.id
        
    partner_id = fields.Many2one('res.partner', string='Partner', required=True, default=_default_partner_id)

class HrExpense(models.Model):

    _name = "hr.expense"
    _inherit = 'hr.expense'
    
    vendor_id = fields.Many2one('res.partner', string="Vendor", domain=[('supplier', '=', True)], readonly=True, states={'draft': [('readonly', False)], 'refused': [('readonly', False)]})

    @api.multi
    def submit_expenses(self):
        if any(expense.state != 'draft' for expense in self):
            raise UserError(_("You cannot report twice the same line!"))
        if len(self.mapped('employee_id')) != 1:
            raise UserError(_("You cannot report expenses for different employees in the same report!"))
        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'hr.expense.sheet',
            'target': 'current',
            'context': {
                'default_expense_line_ids': [line.id for line in self],
                'default_employee_id': self[0].employee_id.id,
                'default_name': self[0].name if len(self.ids) == 1 else '',
                'default_vendor_id' :  self[0].vendor_id.id if self[0].vendor_id else ''
            }
        }
    
    def _prepare_move_line(self, line):
        '''
        This function prepares move line of account.move related to an expense
        '''
        if self.payment_mode == 'company_account':
            partner_id = self.vendor_id.id
        else:
            partner_id = self.employee_id.address_home_id.commercial_partner_id.id
        return {
            'date_maturity': line.get('date_maturity'),
            'partner_id': partner_id,
            'name': line['name'][:64],
            'debit': line['price'] > 0 and line['price'],
            'credit': line['price'] < 0 and - line['price'],
            'account_id': line['account_id'],
            'analytic_line_ids': line.get('analytic_line_ids'),
            'amount_currency': line['price'] > 0 and abs(line.get('amount_currency')) or - abs(line.get('amount_currency')),
            'currency_id': line.get('currency_id'),
            'tax_line_id': line.get('tax_line_id'),
            'tax_ids': line.get('tax_ids'),
            'quantity': line.get('quantity', 1.00),
            'product_id': line.get('product_id'),
            'product_uom_id': line.get('uom_id'),
            'analytic_account_id': line.get('analytic_account_id'),
            'payment_id': line.get('payment_id'),
            'expense_id': line.get('expense_id'),
        }
    
    def action_move_create(self):
        '''
        main function that is called when trying to create the accounting entries related to an expense
        '''
        move_group_by_sheet = {}
        for expense in self:
            #journal = expense.sheet_id.bank_journal_id if expense.payment_mode == 'company_account' else expense.sheet_id.journal_id
            journal = expense.sheet_id.journal_id
            #create the move that will contain the accounting entries
            acc_date = expense.sheet_id.accounting_date or expense.date
            if not expense.sheet_id.id in move_group_by_sheet:
                move = self.env['account.move'].create({
                    'journal_id': journal.id,
                    'company_id': self.env.user.company_id.id,
                    'date': acc_date,
                    'ref': expense.sheet_id.name,
                    # force the name to the default value, to avoid an eventual 'default_name' in the context
                    # to set it to '' which cause no number to be given to the account.move when posted.
                    'name': '/',
                })
                move_group_by_sheet[expense.sheet_id.id] = move
            else:
                move = move_group_by_sheet[expense.sheet_id.id]
            company_currency = expense.company_id.currency_id
            diff_currency_p = expense.currency_id != company_currency
            #one account.move.line per expense (+taxes..)
            move_lines = expense._move_line_get()

            #create one more move line, a counterline for the total on payable account
            payment_id = False
            total, total_currency, move_lines = expense._compute_expense_totals(company_currency, move_lines, acc_date)
#             if expense.payment_mode == 'company_account':
#                 if not expense.sheet_id.bank_journal_id.default_credit_account_id:
#                     raise UserError(_("No credit account found for the %s journal, please configure one.") % (expense.sheet_id.bank_journal_id.name))
#                 emp_account = expense.sheet_id.bank_journal_id.default_credit_account_id.id
#                 journal = expense.sheet_id.bank_journal_id
#                 #create payment
#                 payment_methods = (total < 0) and journal.outbound_payment_method_ids or journal.inbound_payment_method_ids
#                 journal_currency = journal.currency_id or journal.company_id.currency_id
#                 payment = self.env['account.payment'].create({
#                     'payment_method_id': payment_methods and payment_methods[0].id or False,
#                     'payment_type': total < 0 and 'outbound' or 'inbound',
#                     'partner_id': expense.employee_id.address_home_id.commercial_partner_id.id,
#                     'partner_type': 'supplier',
#                     'journal_id': journal.id,
#                     'payment_date': expense.date,
#                     'state': 'reconciled',
#                     'currency_id': diff_currency_p and expense.currency_id.id or journal_currency.id,
#                     'amount': diff_currency_p and abs(total_currency) or abs(total),
#                     'name': expense.name,
#                 })
#                 payment_id = payment.id
#             else:
            if expense.payment_mode == 'company_account':
                emp_account = expense.vendor_id.property_account_payable_id.id
            else:
                if not expense.employee_id.address_home_id:
                    raise UserError(_("No Home Address found for the employee %s, please configure one.") % (expense.employee_id.name))
                emp_account = expense.employee_id.address_home_id.property_account_payable_id.id

            aml_name = expense.employee_id.name + ': ' + expense.name.split('\n')[0][:64]
            move_lines.append({
                    'type': 'dest',
                    'name': aml_name,
                    'price': total,
                    'account_id': emp_account,
                    'date_maturity': acc_date,
                    'amount_currency': diff_currency_p and total_currency or False,
                    'currency_id': diff_currency_p and expense.currency_id.id or False,
                    'payment_id': payment_id,
                    'expense_id': expense.id,
                    })

            #convert eml into an osv-valid format
            lines = [(0, 0, expense._prepare_move_line(x)) for x in move_lines]
            move.with_context(dont_create_taxes=True).write({'line_ids': lines})
            expense.sheet_id.write({'account_move_id': move.id})
#             if expense.payment_mode == 'company_account':
#                 expense.sheet_id.paid_expense_sheets()
        for move in move_group_by_sheet.values():
            move.post()
        return True
    
class HrExpenseSheet(models.Model):
    _name = "hr.expense.sheet"
    _inherit = 'hr.expense.sheet'
    
    vendor_id = fields.Many2one('res.partner', string="Vendor", domain=[('supplier', '=', True)], readonly=True, states={'draft': [('readonly', False)], 'refused': [('readonly', False)]})
    @api.multi
    def action_sheet_move_create(self):
        if any(sheet.state != 'approve' for sheet in self):
            raise UserError(_("You can only generate accounting entry for approved expense(s)."))

        if any(not sheet.journal_id for sheet in self):
            raise UserError(_("Expenses must have an expense journal specified to generate accounting entries."))

        expense_line_ids = self.mapped('expense_line_ids')\
            .filtered(lambda r: not float_is_zero(r.total_amount, precision_rounding=(r.currency_id or self.env.user.company_id.currency_id).rounding))
        res = expense_line_ids.action_move_create()

        if not self.accounting_date:
            self.accounting_date = self.account_move_id.date
 
        if expense_line_ids:
            self.write({'state': 'post'})
        else:
            self.write({'state': 'done'})
        return res
    
    

class Picking(models.Model):
    _name = "stock.picking"
    _inherit = 'stock.picking'
    
    def _default_owner(self):
        return self.env.context.get('default_employee_id') or self.env['res.users'].browse(self.env.uid).partner_id
    
    owner_id = fields.Many2one('res.partner', 'Owner',
        states={'done': [('readonly', True)], 'cancel': [('readonly', True)]}, default=_default_owner,
        help="Default Owner")

class CrossoveredBudgetLines(models.Model):
    _name = "crossovered.budget.lines"
    _inherit = ['crossovered.budget.lines']
    
    allowed_amount = fields.Float(compute='_compute_allowed_amount', string='Allowed Amount', digits=0)
    commitments = fields.Float(compute='_compute_commitments', string='Commitments', digits=0)
    
    @api.multi
    def _compute_allowed_amount(self):
        for line in self:
            line.allowed_amount = line.theoritical_amount + float((line.practical_amount or 0.0)) + float((line.commitments or 0.0))
    
    @api.multi
    def _compute_commitments(self):
        for line in self:
            result = 0.0
            acc_ids = line.general_budget_id.account_ids.ids
            date_to = self.env.context.get('wizard_date_to') or line.date_to
            date_from = self.env.context.get('wizard_date_from') or line.date_from
            if line.analytic_account_id.id:
                self.env.cr.execute("""
                    SELECT sum(price_total) 
                    from purchase_order_line 
                    WHERE account_analytic_id=%s
                    AND account_id=ANY(%s)
                    AND order_id in (SELECT id FROM purchase_order WHERE state in ('done','purchase') 
                    and invoice_status != 'invoiced'
                    and date_order between to_date(%s,'yyyy-mm-dd') AND to_date(%s,'yyyy-mm-dd'))""",
                        (line.analytic_account_id.id, acc_ids, date_from, date_to,))
                result = self.env.cr.fetchone()[0] or 0.0

            line.commitments = -(result)


class PurchaseOrder(models.Model):
    _name = "purchase.order"
    _inherit = ['purchase.order']
    
    state = fields.Selection([
        ('draft', 'RFQ'),
        ('sent', 'RFQ Sent'),
        ('to approve', 'To Approve'),
        ('submit', 'Manager Approval'),
        ('purchase', 'Purchase Order'),
        ('done', 'Locked'),
        ('cancel', 'Cancelled')
        ], string='Status', readonly=True, index=True, copy=False, default='draft', track_visibility='onchange')
    
    @api.multi
    def button_submit(self):
        self.write({'state': 'submit'})
        return {}
    
    @api.multi
    def _check_budget(self):
        for line in self.order_line:
            budget_line = self.env['crossovered.budget.lines'].search([('analytic_account_id', '=', line.account_analytic_id.id)],limit=1)
            if line.price_total > budget_line.allowed_amount:
                raise UserError(_(line.product_id.name + ' has exceeded your budget, Please reduce your request or notify Finance to increase your budget'))
        return True
    
    @api.multi
    def button_confirm(self):
        for order in self:
            if order.state not in ['draft','submit', 'sent']:
                continue
            order._add_supplier_to_product()
            self._check_budget()
            # Deal with double validation process
            if order.company_id.po_double_validation == 'one_step'\
                    or (order.company_id.po_double_validation == 'two_step'\
                        and order.amount_total < self.env.user.company_id.currency_id.compute(order.company_id.po_double_validation_amount, order.currency_id))\
                    or order.user_has_groups('purchase.group_purchase_manager'):
                order.button_approve()
            else:
                order.write({'state': 'to approve'})
        return True

    
class PurchaseOrderLine(models.Model):
    _name = "purchase.order.line"
    _inherit = ['purchase.order.line']
    
    account_id = fields.Many2one('account.account', related='product_id.property_account_expense_id', string='Account', required=False, store=True, readonly=True)


class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ['sale.order']
    _description = "Quotation"
    
    @api.depends('order_line.price_total')
    def _amount_all(self):
        """
        Compute the total amounts of the SO.
        """
        for order in self:
            amount_untaxed = amount_tax = amount_nrc = amount_mrc = 0.0
            for line in order.order_line:
                if line.nrc_mrc == "MRC":
                    amount_mrc += line.price_subtotal
                else:
                    amount_nrc += line.price_subtotal
                amount_untaxed += line.price_subtotal
                amount_tax += line.price_tax
            order.update({
                'amount_untaxed': order.pricelist_id.currency_id.round(amount_untaxed),
                'amount_mrc': order.pricelist_id.currency_id.round(amount_mrc),
                'amount_nrc': order.pricelist_id.currency_id.round(amount_nrc),
                'amount_tax': order.pricelist_id.currency_id.round(amount_tax),
                'amount_total': amount_untaxed + amount_tax,
            })
    
    remarks = fields.Char('Remarks', track_visibility='onchange')
    period = fields.Integer('Service Contract Period (in months)', default="1", required=True, track_visibility='onchange')
    amount_nrc = fields.Monetary(string='Total NRC', store=True, readonly=True, compute='_amount_all', track_visibility='onchange')
    amount_mrc = fields.Monetary(string='Total MRC', store=True, readonly=True, compute='_amount_all', track_visibility='onchange')
    
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


