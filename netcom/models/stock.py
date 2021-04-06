# -*- coding: utf-8 -*-
import datetime
import json

from datetime import date, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError, ValidationError
from odoo.tools import float_is_zero

from functools import partial
from odoo.tools.misc import formatLang

from dateutil.relativedelta import relativedelta
import logging
from werkzeug import url_encode

from odoo import tools

#from odoo.addons import decimal_precision as dp

_logger = logging.getLogger(__name__)



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
    
    @api.one
    @api.constrains('amounts')
    def _check_amount(self):
        if not self.amounts > 0.0:
            raise ValidationError(_('The payment amount must be strictly positive.'))
    
    @api.model
    def _default_payment_amount(self):
        context = dict(self._context or {})
        active_ids = context.get('active_ids', [])
        expense_sheet = self.env['hr.expense.sheet'].browse(active_ids)
        if expense_sheet.payment_mode == 'own_account':
            return expense_sheet.exp_amount_due
        else:
            return expense_sheet.exp_amount_due
    
    @api.one
    @api.depends('amounts', 'test_amount', 'payment_date', 'currency_id')
    def _compute_payment_difference(self):
        if self.amounts:
            self.payment_difference = self.test_amount - self.amounts
    
    def _get_payment_vals(self):
        """ Hook for extension """
        return {
            'partner_type': 'supplier',
            'payment_type': 'outbound',
            'partner_id': self.partner_id.id,
            'journal_id': self.journal_id.id,
            'company_id': self.company_id.id,
            'payment_method_id': self.payment_method_id.id,
            'amount': self.amounts,
            'currency_id': self.currency_id.id,
            'payment_date': self.payment_date,
            'communication': self.communication
        }
    
    amounts = fields.Monetary(string='Payment Amounts', required=True, default=_default_payment_amount)
    test_amount = fields.Monetary(string='Payment Amounts', required=True, default=_default_payment_amount)
    payment_difference = fields.Monetary(compute='_compute_payment_difference', readonly=True)
    payment_difference_handling = fields.Selection([('open', 'set open'), ('reconcile', 'Leave as posted')], default='open', string="Payment Difference", copy=False)
    
    
    @api.multi
    def expense_post_payment(self):
        self.ensure_one()
        context = dict(self._context or {})
        active_ids = context.get('active_ids', [])
        expense_sheet = self.env['hr.expense.sheet'].browse(active_ids)

        # Create payment and post it
        payment = self.env['account.payment'].create(self._get_payment_vals())
        payment.post()

        # Log the payment in the chatter
        body = (_("A payment of %s %s with the reference <a href='/mail/view?%s'>%s</a> related to your expense %s has been made.") % (payment.amount, payment.currency_id.symbol, url_encode({'model': 'account.payment', 'res_id': payment.id}), payment.name, expense_sheet.name))
        expense_sheet.message_post(body=body)
        
        #update amount due
        expense_sheet.exp_amount_due = self.payment_difference
        
        if not self.payment_difference == 0.00 and self.payment_difference_handling == 'open':
            expense_sheet.state = "open"
        
        # Reconcile the payment and the expense, i.e. lookup on the payable account move lines
        account_move_lines_to_reconcile = self.env['account.move.line']
        for line in payment.move_line_ids + expense_sheet.account_move_id.line_ids:
            if line.account_id.internal_type == 'payable':
                account_move_lines_to_reconcile |= line
        account_move_lines_to_reconcile.reconcile()

        return {'type': 'ir.actions.act_window_close'}
    
    
class HrExpense(models.Model):

    _name = "hr.expense"
    _inherit = 'hr.expense'
    
    def _default_analytic(self):
        return self.env['account.analytic.account'].search([('name','=','Netcom')])
    #     return self.env['ir.property'].get('property_analytic_account_id', 'hr.expense')
    
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account', default=_default_analytic, states={'post': [('readonly', True)], 'done': [('readonly', True)]}, oldname='analytic_account')
    #analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account', default=lambda self: self.env['ir.property'].get('property_analytic_account_id', 'hr.expense'), states={'post': [('readonly', True)], 'done': [('readonly', True)]}, oldname='analytic_account')
    vendor_id = fields.Many2one('res.partner', string="Vendor", domain=[('supplier', '=', True)], readonly=True, states={'draft': [('readonly', False)], 'refused': [('readonly', False)]})
    need_override = fields.Boolean ('Need Budget Override', track_visibility="onchange")
    override_budget = fields.Boolean ('Override Budget', track_visibility="onchange")
    
    @api.multi
    def action_override_budget(self):
        self.write({'override_budget': True})
        if self.sheet_id.need_override == False:
            subject = "Budget Override Done, Expense {} can be approved now".format(self.name)
            partner_ids = []
            for partner in self.sheet_id.message_partner_ids:
                partner_ids.append(partner.id)
            self.sheet_id.message_post(subject=subject,body=subject,partner_ids=partner_ids)
    
    '''
    @api.multi
    def _check_operations_department(self):
        if self.employee_id.department_id.parent_id.name == "Administration":
            group_id = self.env['ir.model.data'].xmlid_to_object('netcom.group_hr_leave_manager')
            user_ids = []
            partner_ids = []
            for user in group_id.users:
                user_ids.append(user.id)
                partner_ids.append(user.partner_id.id)
            self.message_subscribe_users(user_ids=user_ids)
            subject = "Leave Request for {} is Ready for Second Approval".format(self.display_name)
            self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
            return False
    '''
    
    @api.multi
    def submit_expenses(self):
        #self._check_operations_department()
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
    
    @api.multi
    def _check_override(self):
        for self in self:
            for line in self.expense_line_ids:
                if line.need_override and line.override_budget == False:
                    self.need_override = True
                else:
                    self.need_override = False
    
    @api.one
    @api.depends('expense_line_ids', 'expense_line_ids.total_amount', 'expense_line_ids.currency_id')
    def _compute_amount(self):
        total_amount = 0.0
        for expense in self.expense_line_ids:
            total_amount += expense.currency_id.with_context(
                date=expense.date,
                company_id=expense.company_id.id
            ).compute(expense.total_amount, self.currency_id)
        self.total_amount = total_amount
        if self.state in ['done']:
            self.exp_amount_due = 0
        else:
            self.exp_amount_due = total_amount
    
    vendor_id = fields.Many2one('res.partner', string="Vendor", domain=[('supplier', '=', True)], readonly=True, states={'draft': [('readonly', False)], 'refused': [('readonly', False)]})
    need_override = fields.Boolean ('Need Budget Override', compute= "_check_override", track_visibility="onchange")
    expense_line_ids = fields.One2many('hr.expense', 'sheet_id', string='Expense Lines', states={'done': [('readonly', True)], 'post': [('readonly', True)]}, copy=False)
    exp_amount_due = fields.Float(string='Amount Due', store=True, readonly=False, compute='_compute_amount')
    
    state = fields.Selection([('submit', 'Submitted'),
                              ('approve', 'Approved'),
                              ('post', 'Posted'),
                              ('open', 'Open'),
                              ('done', 'Paid'),
                              ('cancel', 'Refused')
                              ], string='Status', index=True, readonly=False, track_visibility='onchange', copy=False, default='submit', required=True,
    help='Expense Report State')
    
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
    
    @api.multi
    def approve_expense_sheets(self):
        current_employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        if not self.user_has_groups('netcom.group_hr_line_manager'):
            raise UserError(_("Only Line Managers can approve expenses"))
        if current_employee == self.employee_id:
            raise UserError(_('Only your line manager can approve your Expenses'))
        if self._check_budget() == False and self.need_override:
            return {}
        
        self.write({'state': 'approve', 'responsible_id': self.env.user.id})
    
    @api.multi
    def unpost_expense_sheets(self):
        self.mapped('expense_line_ids').write({'is_refused': False})
        move_id = self.account_move_id
        if self.account_move_id:
            # cancel posted entry from Vendor Bills [account_move.py -> button_cancel()]
            self.account_move_id.button_cancel()
            self.account_move_id = False
            # unlink/delete posted entry [account_move.py -> unlink()]
            move_id.unlink()
        return self.write({'state': 'approve'})
        
    @api.multi
    def _check_budget(self):
        override = False
        for line in self.expense_line_ids:
            self.env.cr.execute("""
                    SELECT * FROM crossovered_budget_lines WHERE
                    general_budget_id in (SELECT budget_id FROM account_budget_rel WHERE account_id=%s) AND
                    analytic_account_id = %s AND 
                    to_date(%s,'yyyy-mm-dd') between date_from and date_to""",
                    (line.account_id.id,line.analytic_account_id.id, line.date))
            result = self.env.cr.fetchone()
            if result:
                result = self.env['crossovered.budget.lines'].browse(result[0]) 
                if line.total_amount > result.allowed_amount and line.override_budget == False:
                    override = True
                    line.write({'need_override': True})
            else:
                if line.override_budget == False:
                    override = True
                    line.write({'need_override': True})
        if override:
            group_id = self.env['ir.model.data'].xmlid_to_object('netcom.group_sale_account_budget')
            user_ids = []
            partner_ids = []
            for user in group_id.users:
                user_ids.append(user.id)
                partner_ids.append(user.partner_id.id)
            self.message_subscribe_users(user_ids=user_ids)
            subject = "Expense {} needs a budget override".format(self.name)
            self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
            return False
        return True

    

class Picking(models.Model):
    _name = "stock.picking"
    _inherit = 'stock.picking'
    
    @api.multi
    def manager_confirm(self):
        for order in self:
            order.write({'man_confirm': True})
        return True
    
    def _default_owner(self):
        return self.env.context.get('default_employee_id') or self.env['res.users'].browse(self.env.uid).partner_id
    
    def _default_employee(self):
        self.env['hr.employee'].search([('user_id','=',self.env.uid)])
        return self.env['hr.employee'].search([('user_id','=',self.env.uid)])
    
    owner_id = fields.Many2one('res.partner', 'Owner',
        states={'done': [('readonly', True)], 'cancel': [('readonly', True)]}, default=_default_owner,
        help="Default Owner")
    
    employee_id = fields.Many2one('hr.employee', 'Employee',
        states={'done': [('readonly', True)], 'cancel': [('readonly', True)]}, default=_default_employee,
        help="Default Owner")
    
    sub_account_id = fields.Many2one('sub.account', string='Child Account', index=True, ondelete='cascade')
    man_confirm = fields.Boolean('Manager Confirmation', track_visibility='onchange')
    net_lot_id = fields.Many2one(string="Serial Number", related="move_line_ids.lot_id", readonly=True)
    internal_transfer = fields.Boolean('Internal Transfer?', track_visibility='onchange')
    x_studio_field_KZL4m = fields.Many2one('res.partner', string='Client', index=True, ondelete='cascade', required=False)
    
    rejection_reason = fields.Many2one('stock.rejection.reason', string='Rejection Reason', index=True, track_visibility='onchange')
    
    fixed_assets_movement = fields.Boolean('Fixed Assets Movement', track_visibility='onchange')
    
    location_dest_id = fields.Many2one(
        'stock.location', "Destination Location",
        default=lambda self: self.env['stock.picking.type'].browse(self._context.get('default_picking_type_id')).default_location_dest_id,
        readonly=True, required=True,
        states={'draft': [('readonly', False)], 'confirmed': [('readonly', False)], 'assigned': [('readonly', False)]})
    
    @api.multi
    def button_reset(self):
        self.mapped('move_lines')._action_cancel()
        self.write({'state': 'draft'})
        return {}
    
    @api.model
    def create(self, vals):
        a = super(Picking, self).create(vals)
        a.send_store_request_mail()
        return a
        return super(Picking, self).create(vals)
    
    @api.multi
    def send_store_request_mail(self):
        if self.state in ['draft','waiting','confirmed']:
            group_id = self.env['ir.model.data'].xmlid_to_object('stock.group_stock_manager')
            user_ids = []
            partner_ids = []
            for user in group_id.users:
                user_ids.append(user.id)
                partner_ids.append(user.partner_id.id)
            self.message_subscribe_users(user_ids=user_ids)
            subject = "A new {} , {} has been made".format(self.picking_type_id.name, self.name)
            self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
            return False
        return True
    
    @api.multi
    def send_store_request_done_mail(self):
        if self.state in ['done']:
            subject = "Store request {} has been approved and validated".format(self.name)
            partner_ids = []
            for partner in self.message_partner_ids:
                partner_ids.append(partner.id)
            self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
            
    @api.multi
    def send_store_request_rejected_mail(self):
        #if self.state in ['done']:
        subject = "Store request {} has been Rejected because {} ".format(self.name, self.rejection_reason.name)
        partner_ids = []
        for partner in self.message_partner_ids:
            partner_ids.append(partner.id)
        self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
    
    
    @api.multi
    def send_store_request_products_recieved_message(self):
        current_employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        if not current_employee == self.employee_id:
            raise UserError(_("You can't confirm receipt of an item you didn't request."))
        else:
            if self.state in ['done']:
                subject = "Store request Products for {} has been approved and recieved by Me {}".format(self.name, self.employee_id)
                partner_ids = []
                for partner in self.message_partner_ids:
                    partner_ids.append(partner.id)
                self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
            else:
                raise UserError(_("Store request hasn't been validated"))
    
    @api.multi
    def create_purchase_order(self):
        """
        Method to open create purchase order form
        """

        partner_id = self.x_studio_field_KZL4m
        client_id = self.x_studio_field_KZL4m
        sub_account_id = self.sub_account_id
        #product_id = self.move_lines.product_id
             
        view_ref = self.env['ir.model.data'].get_object_reference('purchase', 'purchase_order_form')
        view_id = view_ref[1] if view_ref else False
        
        #purchase_line_obj = self.env['purchase.order.line']
        for subscription in self:
            order_lines = []
            for line in subscription.move_lines:
                order_lines.append((0, 0, {
                    'name': line.product_id.name,
                    'product_uom': line.product_id.uom_id.id,
                    'product_id': line.product_id.id,
                    'account_id': line.account_id.id,
                    'product_qty': line.product_uom_qty,
                    'date_planned': date.today(),
                    'price_unit': line.product_id.standard_price,
                }))
         
        res = {
            'type': 'ir.actions.act_window',
            'name': ('Purchase Order'),
            'res_model': 'purchase.order',
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': view_id,
            'target': 'current',
            'context': {'default_client_id': client_id.id, 'default_sub_account_id': sub_account_id.id, 'default_stock_source': self.name, 'default_order_line': order_lines}
        }
        
        return res
    
class StockRejectionReason(models.Model):
    _name = "stock.rejection.reason"
    _description = 'Reason for Rejecting Requests'

    name = fields.Char('Name', required=True, translate=True)
    active = fields.Boolean('Active', default=True)
    
    
class StockPickingRejection(models.TransientModel):
    _name = 'stock.picking.rejected'
    _description = 'Get Rejection Reason'

    rejection_reason_id = fields.Many2one('stock.rejection.reason', 'Rejection Reason')

    @api.multi
    def action_rejection_reason_apply(self):
        leads = self.env['stock.picking'].browse(self.env.context.get('active_ids'))
        leads.write({'rejection_reason': self.rejection_reason_id.id})
        leads.send_store_request_rejected_mail()
        return leads.button_reset()
    
      
class CrossoveredBudgetLines(models.Model):
    _name = "crossovered.budget.lines"
    _inherit = ['crossovered.budget.lines']
    _order = "general_budget_id"
    
    allowed_amount = fields.Float(compute='_compute_allowed_amount', string='Allowed Amount', digits=0, store=False)
    commitments = fields.Float(compute='_compute_commitments', string='Commitments', digits=0, store=False)
    dept_id = fields.Many2one('hr.department', 'Department',related='general_budget_id.department_id', store=True, readonly=False, copy=False)
    
    practical_amount = fields.Float(compute='_compute_practical_amount', string='Practical Amount', digits=0, store=False)
    theoritical_amount = fields.Float(compute='_compute_theoritical_amount', string='Theoretical Amount', digits=0, store=False)
    percentage = fields.Float(compute='_compute_percentage', string='Achievement', store=False)
    '''
    dept_id = fields.Many2one(
        comodel_name='account.budget.post')
    department = fields.Many2one(
        comodel_name='hr.department',
        related = 'dept_id.department_id',
        string='Department')
    '''
    @api.multi
    def _compute_theoritical_amount(self):
        today = fields.Datetime.now()
        for line in self:
            # Used for the report

            if self.env.context.get('wizard_date_from') and self.env.context.get('wizard_date_to'):
                date_from = fields.Datetime.from_string(self.env.context.get('wizard_date_from'))
                date_to = fields.Datetime.from_string(self.env.context.get('wizard_date_to'))
                if date_from < fields.Datetime.from_string(line.date_from):
                    date_from = fields.Datetime.from_string(line.date_from)
                elif date_from > fields.Datetime.from_string(line.date_to):
                    date_from = False

                if date_to > fields.Datetime.from_string(line.date_to):
                    date_to = fields.Datetime.from_string(line.date_to)
                elif date_to < fields.Datetime.from_string(line.date_from):
                    date_to = False

                theo_amt = 0.00
                if date_from and date_to:
                    line_timedelta = fields.Datetime.from_string(line.date_to) - fields.Datetime.from_string(line.date_from)
                    elapsed_timedelta = date_to - date_from
                    if elapsed_timedelta.days > 0:
                        theo_amt = (elapsed_timedelta.total_seconds() / line_timedelta.total_seconds()) * line.planned_amount
            else:
                if line.paid_date:
                    if fields.Datetime.from_string(line.date_to) <= fields.Datetime.from_string(line.paid_date):
                        theo_amt = 0.00
                    else:
                        theo_amt = line.planned_amount
                else:
                    line_timedelta = fields.Datetime.from_string(line.date_to) - fields.Datetime.from_string(line.date_from)
                    elapsed_timedelta = fields.Datetime.from_string(today) - (fields.Datetime.from_string(line.date_from))

                    if elapsed_timedelta.days < 0:
                        # If the budget line has not started yet, theoretical amount should be zero
                        theo_amt = 0.00
                    
                    elif line_timedelta.days > 0 and fields.Datetime.from_string(today) < fields.Datetime.from_string(line.date_to):
                        month_dif =int(str(fields.Datetime.from_string(today))[5:7]) - int(str(line.date_from)[5:7]) + 1
                        if month_dif < 1:
                            month_dif =(int(str(fields.Datetime.from_string(today))[5:7]) + (12-int(str(line.date_from)[5:7]))) + 1
#                         interval = int(str(line.date_to)[5:7]) - int(str(line.date_from)[5:7]) + 1
                        interval = 12
                        theo_amt =  (line.planned_amount/interval) * month_dif
                    else:
                        theo_amt = line.planned_amount

            line.theoritical_amount = theo_amt
    
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
                
                self.env.cr.execute("""
                    SELECT sum(total_amount) 
                    from hr_expense 
                    WHERE analytic_account_id=%s
                    AND account_id=ANY(%s)
                    AND sheet_id in (SELECT id FROM hr_expense_sheet WHERE state = 'approve') 
                    and date between to_date(%s,'yyyy-mm-dd') AND to_date(%s,'yyyy-mm-dd')""",
                        (line.analytic_account_id.id, acc_ids, date_from, date_to,))
                result2 = self.env.cr.fetchone()[0] or 0.0
                
            line.commitments = -(result+result2)


class PurchaseOrder(models.Model):
    _name = "purchase.order"
    _inherit = ['purchase.order']
    
    def _default_employee(self):
        self.env['hr.employee'].search([('user_id','=',self.env.uid)])
        return self.env['hr.employee'].search([('user_id','=',self.env.uid)])
    
    @api.multi
    def _check_override(self):
        for self in self:
            for line in self.order_line:
                if line.need_override and line.override_budget == False:
                    self.need_override = True
                else:
                    self.need_override = False
                    
    need_override = fields.Boolean ('Need Budget Override', compute= "_check_override", track_visibility="onchange")
    employee_id = fields.Many2one('hr.employee', 'Employee',
        states={'done': [('readonly', True)], 'cancel': [('readonly', True)]}, default=_default_employee)
    sub_account_id = fields.Many2one('sub.account', string='Sub Account', index=True, ondelete='cascade')
    approval_date = fields.Date(string='Manager Approval Date', readonly=True, track_visibility='onchange')
    manager_approval = fields.Many2one('res.users','Manager Approval Name', readonly=True, track_visibility='onchange')
    client_id = fields.Many2one('res.partner','Client', track_visibility='onchange')
    
    department_name = fields.Char(string="Department", related="employee_id.department_id.name", readonly=True)
    
    state = fields.Selection([
        ('draft', 'RFQ'),
        ('sent', 'RFQ Sent'),
        ('to approve', 'To Approve'),
        ('submit', 'Manager Approval'),
        ('purchase', 'Purchase Order'),
        ('done', 'Locked'),
        ('cancel', 'Cancelled')
        ], string='Status', readonly=True, index=True, copy=False, default='draft', track_visibility='onchange')
    
    stock_source = fields.Char(string='Source document')
    active = fields.Boolean('Active', default=True)
    
    @api.multi
    def button_submit(self):
        self.write({'state': 'submit'})
        return {}
    
    @api.multi
    def _check_budget(self):
        override = False
        for line in self.order_line:
            self.env.cr.execute("""
                    SELECT * FROM crossovered_budget_lines WHERE
                    general_budget_id in (SELECT budget_id FROM account_budget_rel WHERE account_id=%s) AND
                    analytic_account_id = %s AND 
                    to_date(%s,'yyyy-mm-dd') between date_from and date_to""",
                    (line.account_id.id,line.account_analytic_id.id, line.order_id.date_order))
            result = self.env.cr.fetchone()
            if result:
                result = self.env['crossovered.budget.lines'].browse(result[0])  
                if line.price_total > result.allowed_amount and line.override_budget == False:
                    override = True
                    line.write({'need_override': True})
            else:
                if line.override_budget == False:
                    override = True
                    line.write({'need_override': True})
        if override:
            group_id = self.env['ir.model.data'].xmlid_to_object('netcom.group_sale_account_budget')
            user_ids = []
            partner_ids = []
            for user in group_id.users:
                user_ids.append(user.id)
                partner_ids.append(user.partner_id.id)
            self.message_subscribe_users(user_ids=user_ids)
            subject = "Purchase Order {} needs a budget override".format(self.name)
            self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
            return False
        return True
    
    @api.multi
    def _check_po_employee_department(self):
        current_employee = self.env['hr.employee'].search([('user_id', '=', self.env.uid)], limit=1)
        print(current_employee)
        if current_employee.id == 1446 and self.employee_id.department_id.id == 24:
            self.write({'state': 'to approve'})
            #raise UserError(_('You are currently not allowed to Confirm your departments purchase orders'))
    
    @api.multi
    def cost_valuation_update(self):
        for line in self.order_line:
            line.product_id.standard_price = line.price_unit
            line.product_id.currency_id = self.currency_id
        
    @api.multi
    def button_approve(self):
        res = super(PurchaseOrder, self).button_approve()
        self._check_po_employee_department()
        return res
    
    @api.multi
    def button_confirm(self):
        for order in self:
            if order.state not in ['draft','submit', 'sent']:
                continue
            if self._check_budget() == False and self.need_override:
                return {}
            self.approval_date = date.today()
            self.manager_approval = self._uid
            #order.cost_valuation_update()
            order._add_supplier_to_product()
            # Deal with double validation process
            if order.company_id.po_double_validation == 'one_step'\
                    or (order.company_id.po_double_validation == 'two_step'\
                        and order.amount_total < self.env.user.company_id.currency_id.compute(order.company_id.po_double_validation_amount, order.currency_id))\
                    or order.user_has_groups('purchase.group_purchase_manager'):
                order.button_approve()
            else:
                order.write({'state': 'to approve'})
        return True
    
    #NOT TO BE USED YET AND DO NOT DELETE THIS 
    """@api.multi
    def button_approve(self):
        super(PurchaseOrder, self).button_approve()
        for order in self:
            for order_line in order.order_line:
                order_line.product_id.standard_price = order_line.price_unit
    """

    
    @api.multi
    def button_reset(self):
        self.mapped('order_line')
        self.write({'state': 'draft'})
        return {}

    @api.multi
    def copy(self, default=None):
        new_po = super(PurchaseOrder, self).copy(default=default)
        for line in new_po.order_line:
            seller = line.product_id._select_seller(
                partner_id=line.partner_id, quantity=line.product_qty,
                date=line.order_id.date_order and line.order_id.date_order[:10], uom_id=line.product_uom)
            line.date_planned = line._get_date_planned(seller)
            line.write({'need_override': False})
            line.write({'override_budget': False})
        return new_po

class NetcomPurchaseRequisitionLine(models.Model):
    _name = "purchase.requisition.line"
    _inherit = ['purchase.requisition.line']
    
    account_analytic_id = fields.Many2one('account.analytic.account', string='Analytic Account', required=True)
        
class PurchaseOrderLine(models.Model):
    _name = "purchase.order.line"
    _inherit = ['purchase.order.line']
    
    def _default_analytic(self):
        return self.env['account.analytic.account'].search([('name','=','Netcom')])
    
    def _default_account(self):
        return self.product_id.property_account_expense_id
#     
#     @api.multi
#     @api.onchange('type')
#     def type_change(self):
#         self.product_id = False
    
    account_analytic_id = fields.Many2one('account.analytic.account', string='Analytic Account', required=True, default=_default_analytic, track_visibility="always")
    account_id = fields.Many2one('account.account', string='Account',  domain = [('user_type_id', 'in', [5,8,17,16])])
    need_override = fields.Boolean ('Need Budget Override', track_visibility="onchange")
    override_budget = fields.Boolean ('Override Budget', track_visibility="onchange")
    
    @api.multi
    def action_override_budget(self):
        self.write({'override_budget': True})
        if self.order_id.need_override == False:
            subject = "Budget Override Done, Purchase Order {} can be approved now".format(self.name)
            partner_ids = []
            for partner in self.order_id.message_partner_ids:
                partner_ids.append(partner.id)
            self.order_id.message_post(subject=subject,body=subject,partner_ids=partner_ids)

class AccountAccount(models.Model):
    _inherit = ['account.account']

    active = fields.Boolean('Active', default=True)

class AccountInvoiceReport(models.Model):
    _inherit = ['account.invoice.report']
    
    nrc_mrc = fields.Char('MRC/NRC', readonly=True)
    sub_account_id = fields.Many2one('sub.account', string='Sub Account', readonly=True)
    activation_date = fields.Date(string='Activation Date', readonly=True)
    term_date = fields.Date(string='Termination Date', readonly=True)
    perm_up_date = fields.Date(string='Permanent Upgrade Date', readonly=True)
    asset_category_id = fields.Many2one('account.asset.category', string='Deferred Revenue Type', readonly=True)
    price_review_date = fields.Date(string='Price Review Date', readonly=True)
    
    _depends = {
        'account.invoice': [
            'account_id', 'amount_total_company_signed', 'commercial_partner_id', 'company_id',
            'currency_id', 'date_due', 'date_invoice', 'fiscal_position_id',
            'journal_id', 'partner_bank_id', 'partner_id', 'payment_term_id',
            'residual', 'state', 'type', 'user_id',
        ],
        'account.invoice.line': [
            'account_id', 'invoice_id', 'price_subtotal', 'product_id',
            'quantity', 'uom_id', 'account_analytic_id', 'nrc_mrc', 'sub_account_id','asset_category_id'
        ],
        'product.product': ['product_tmpl_id'],
        'product.template': ['categ_id'],
        'product.uom': ['category_id', 'factor', 'name', 'uom_type'],
        'res.currency.rate': ['currency_id', 'name'],
        'res.partner': ['country_id'],
        'sub.account': ['activation_date'],
        'sub.account': ['price_review_date'],
        'sub.account': ['term_date'],
        'sub.account': ['perm_up_date']
    }
    
    def _select(self):
        select_str = """
            SELECT sub.id, sub.date, sub.product_id,sub.nrc_mrc,sub.sub_account_id, sub.activation_date, sub.price_review_date, sub.asset_category_id, sub.perm_up_date, sub.term_date, sub.partner_id, sub.country_id, sub.account_analytic_id,
                sub.payment_term_id, sub.uom_name, sub.currency_id, sub.journal_id,
                sub.fiscal_position_id, sub.user_id, sub.company_id, sub.nbr, sub.type, sub.state,
                sub.categ_id, sub.date_due, sub.account_id, sub.account_line_id, sub.partner_bank_id,
                sub.product_qty, sub.price_total as price_total, sub.price_average as price_average,
                COALESCE(cr.rate, 1) as currency_rate, sub.residual as residual, sub.commercial_partner_id as commercial_partner_id
        """
        return select_str

    def _sub_select(self):
        select_str = """
                SELECT ail.id AS id,
                    ai.date_invoice AS date,
                    ail.product_id,ail.nrc_mrc,ail.sub_account_id, ail.asset_category_id, sa.activation_date, sa.price_review_date, sa.perm_up_date, sa.term_date, ai.partner_id, ai.payment_term_id, ail.account_analytic_id,
                    u2.name AS uom_name,
                    ai.currency_id, ai.journal_id, ai.fiscal_position_id, ai.user_id, ai.company_id,
                    1 AS nbr,
                    ai.type, ai.state, pt.categ_id, ai.date_due, ai.account_id, ail.account_id AS account_line_id,
                    ai.partner_bank_id,
                    SUM ((invoice_type.sign * ail.quantity) / u.factor * u2.factor) AS product_qty,
                    SUM(ail.price_subtotal_signed * invoice_type.sign) AS price_total,
                    SUM(ABS(ail.price_subtotal_signed)) / CASE
                            WHEN SUM(ail.quantity / u.factor * u2.factor) <> 0::numeric
                               THEN SUM(ail.quantity / u.factor * u2.factor)
                               ELSE 1::numeric
                            END AS price_average,
                    ai.residual_company_signed / (SELECT count(*) FROM account_invoice_line l where invoice_id = ai.id) *
                    count(*) * invoice_type.sign AS residual,
                    ai.commercial_partner_id as commercial_partner_id,
                    partner.country_id
        """
        return select_str
    
    def _from(self):
        from_str = """
                FROM account_invoice_line ail
                JOIN account_invoice ai ON ai.id = ail.invoice_id
                JOIN res_partner partner ON ai.commercial_partner_id = partner.id
                LEFT JOIN product_product pr ON pr.id = ail.product_id
                LEFT JOIN sub_account sa on sa.id = ail.sub_account_id
                left JOIN product_template pt ON pt.id = pr.product_tmpl_id
                LEFT JOIN product_uom u ON u.id = ail.uom_id
                LEFT JOIN product_uom u2 ON u2.id = pt.uom_id
                JOIN (
                    -- Temporary table to decide if the qty should be added or retrieved (Invoice vs Credit Note)
                    SELECT id,(CASE
                         WHEN ai.type::text = ANY (ARRAY['in_refund'::character varying::text, 'in_invoice'::character varying::text])
                            THEN -1
                            ELSE 1
                        END) AS sign
                    FROM account_invoice ai
                ) AS invoice_type ON invoice_type.id = ai.id
        """
        return from_str
    
    def _group_by(self):
        group_by_str = """
                GROUP BY ail.id, sa.activation_date, sa.price_review_date, ail.asset_category_id, sa.perm_up_date, sa.term_date, ail.product_id, ail.account_analytic_id, ai.date_invoice, ai.id,
                    ai.partner_id, ai.payment_term_id, u2.name, u2.id, ai.currency_id, ai.journal_id,
                    ai.fiscal_position_id, ai.user_id, ai.company_id, ai.type, invoice_type.sign, ai.state, pt.categ_id,
                    ai.date_due, ai.account_id, ail.account_id, ai.partner_bank_id, ai.residual_company_signed,
                    ai.amount_total_company_signed, ai.commercial_partner_id, partner.country_id
        """
        return group_by_str
    
class AccountInvoice(models.Model):
    _name = "account.invoice"
    _inherit = ['account.invoice']
    _description = "Invoice"
    
    @api.multi
    def _get_tax_amount_by_group(self):
        self.ensure_one()
        currency = self.currency_id or self.company_id.currency_id
        fmt = partial(formatLang, self.with_context(lang=self.partner_id.lang).env, currency_obj=currency)
        res = {}
        for line in self.tax_line_ids:
            res.setdefault(line.tax_id.tax_group_id, {'base': 0.0, 'amount': 0.0})
            res[line.tax_id.tax_group_id]['amount'] += (line.amount * line.invoice_id.interval)
            res[line.tax_id.tax_group_id]['base'] += line.base
        res = sorted(res.items(), key=lambda l: l[0].sequence)
        res = [(
            r[0].name, r[1]['amount'], r[1]['base'],
            fmt(r[1]['amount']), fmt(r[1]['base']),
        ) for r in res]
        return res
    
#     @api.multi
#     def get_taxes_values(self):
#         tax_grouped = {}
#         for line in self.invoice_line_ids:
#             price_unit = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
#             taxes = line.invoice_line_tax_ids.compute_all((price_unit * self.interval), self.currency_id, line.quantity, line.product_id, self.partner_id)['taxes']
#             for tax in taxes:
#                 val = self._prepare_tax_line_vals(line, tax)
#                 key = self.env['account.tax'].browse(tax['id']).get_grouping_key(val)
#   
#                 if key not in tax_grouped:
#                     tax_grouped[key] = val
#                 else:
#                     tax_grouped[key]['amount'] += val['amount']
#                     tax_grouped[key]['base'] += val['base']
#         return tax_grouped
    
    @api.one
    @api.depends('invoice_line_ids.price_subtotal', 'tax_line_ids.amount', 'tax_line_ids.amount_rounding',
                 'currency_id', 'company_id', 'date_invoice', 'type', 'interval')
    def _compute_amount(self):
        amount_nrc = amount_mrc = 0.0
        for line in self.invoice_line_ids:
            if line.nrc_mrc == "MRC":
                amount_mrc += line.price_subtotal
            else:
                amount_nrc += line.price_subtotal
        self.amount_nrc = amount_nrc
        self.amount_mrc = amount_mrc
        round_curr = self.currency_id.round
        self.amount_untaxed = sum(line.price_subtotal for line in self.invoice_line_ids)
        self.amount_tax = sum(round_curr(line.amount_total) for line in self.tax_line_ids)
#         self.amount_tax = self.amount_tax * self.interval
        self.amount_total = self.amount_untaxed + self.amount_tax
        amount_total_company_signed = self.amount_total
        amount_untaxed_signed = self.amount_untaxed
        if self.currency_id and self.company_id and self.currency_id != self.company_id.currency_id:
            currency_id = self.currency_id.with_context(date=self.date_invoice)
            amount_total_company_signed = currency_id.compute(self.amount_total, self.company_id.currency_id)
            amount_untaxed_signed = currency_id.compute(self.amount_untaxed, self.company_id.currency_id)
        sign = self.type in ['in_refund', 'out_refund'] and -1 or 1
        self.amount_total_company_signed = amount_total_company_signed * sign
        self.amount_total_signed = self.amount_total * sign
        self.amount_untaxed_signed = amount_untaxed_signed * sign
    
    amount_nrc = fields.Monetary(string='Total NRC', store=True, readonly=False, compute='_compute_amount', track_visibility='onchange')
    amount_mrc = fields.Monetary(string='Total MRC', store=True, readonly=False, compute='_compute_amount', track_visibility='onchange')
    interval = fields.Float("Invoice interval", default=1)
    reference_des = fields.Char(related='invoice_line_ids.subscription_id.reference_des', string='Reference/Description')
    
    number = fields.Char(related='move_id.name', store=True, readonly=False, copy=False)
    move_id = fields.Many2one('account.move', string='Journal Entry',
        readonly=True, index=True, ondelete='restrict', copy=False,
        help="Link to the automatically generated Journal Items.")
    state = fields.Selection([
            ('draft','Draft'),
            ('open', 'Open'),
            ('paid', 'Paid'),
            ('cancel', 'Cancelled'),
        ], string='Status', index=True, readonly=False, default='draft',
        track_visibility='onchange', copy=False,
        help=" * The 'Draft' status is used when a user is encoding a new and unconfirmed Invoice.\n"
             " * The 'Open' status is used when user creates invoice, an invoice number is generated. It stays in the open status till the user pays the invoice.\n"
             " * The 'Paid' status is set automatically when the invoice is paid. Its related journal entries may or may not be reconciled.\n"
             " * The 'Cancelled' status is used when user cancel invoice.")
    total_discount_amount = fields.Float(string="Total Discount Amount", compute="_total_discount_amount")
    
    treasury_approval = fields.Boolean(string='payment for approval')
    treasury_approved = fields.Boolean(string='payment approved')
    payment_approval_date = fields.Datetime(string='Payment Approval Date', store=True, readonly=True, track_visibility='onchange')
    
    @api.depends('invoice_line_ids.discount_amount')
    def _total_discount_amount(self):
        total_discount_amount = 0.0
        for line in self.invoice_line_ids:
            self.total_discount_amount += line.discount_amount
    
    @api.multi
    def submit_approved_expenses(self):
        for self in self:
            if self.state == 'open':
                self.treasury_approval = True
                group_id = self.env['ir.model.data'].xmlid_to_object('netcom.group_expense_payment')
                user_ids = []
                partner_ids = []
                for user in group_id.users:
                    user_ids.append(user.id)
                    partner_ids.append(user.partner_id.id)
                self.message_subscribe_users(user_ids=user_ids)
                subject = "Vendor Bill {} is ready for Payment".format(self.number)
                self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
                return False
            else:
                raise UserError(_('Vendor Bill to be Approved for payment has not been Validated.'))
    
    @api.multi
    def button_treasury_approval(self):
        self.treasury_approved = True
        self.treasury_approval = False
        self.payment_approval_date = datetime.datetime.now()
        return {}
    
class AccountInvoiceTax(models.Model):
    _name = "account.invoice.tax"
    _inherit = ['account.invoice.tax']
    
    @api.depends('invoice_id.invoice_line_ids')
    def _compute_base_amount(self):
        tax_grouped = {}
        for invoice in self.mapped('invoice_id'):
            tax_grouped[invoice.id] = invoice.get_taxes_values()
        for tax in self:
            tax.base = 0.0
            if tax.tax_id:
                key = tax.tax_id.get_grouping_key({
                    'tax_id': tax.tax_id.id,
                    'account_id': tax.account_id.id,
                    'account_analytic_id': tax.account_analytic_id.id,
                })
                if tax.invoice_id and key in tax_grouped[tax.invoice_id.id]:
                    tax.base = tax_grouped[tax.invoice_id.id][key]['base']
                    tax.base = (tax.base * tax.invoice_id.interval)
                else:
                    _logger.warning('Tax Base Amount not computable probably due to a change in an underlying tax (%s).', tax.tax_id.name)
                    
    base = fields.Monetary(string='Base', compute='_compute_base_amount', store=True)
    amount_total = fields.Monetary(string="Amount", compute='_compute_amount_total')
    
    @api.depends('amount', 'amount_rounding')
    def _compute_amount_total(self):
        for tax_line in self:
            tax_line.amount_total = (tax_line.amount + tax_line.amount_rounding) * tax_line.invoice_id.interval

class AccountInvoiceLine(models.Model):
    _name = "account.invoice.line"
    _inherit = ['account.invoice.line']
    
    nrc_mrc = fields.Char('MRC/NRC', compute='_compute_mrc_nrc', readonly=False, store=True)
    sub_account_id = fields.Many2one('sub.account', string='Child Account', index=True, ondelete='cascade')
    discount_amount = fields.Float(string="Discount Amount", compute="_compute_discount_amount", store=False)
    
    @api.one
    @api.depends('price_unit', 'discount', 'invoice_line_tax_ids', 'quantity',
        'product_id', 'invoice_id.partner_id', 'invoice_id.currency_id', 'invoice_id.company_id',
        'invoice_id.date_invoice', 'invoice_id.date', 'invoice_id.interval')
    def _compute_price(self):
        currency = self.invoice_id and self.invoice_id.currency_id or None
        price = self.price_unit * (1 - (self.discount or 0.0) / 100.0)
        price = price * self.invoice_id.interval
        taxes = False
        if self.invoice_line_tax_ids:
            taxes = self.invoice_line_tax_ids.compute_all((price), currency, self.quantity, product=self.product_id, partner=self.invoice_id.partner_id)
        self.price_subtotal = price_subtotal_signed = (taxes['total_excluded']) if taxes else self.quantity * price
        self.price_total = taxes['total_included'] if taxes else self.price_subtotal 
        if self.invoice_id.currency_id and self.invoice_id.currency_id != self.invoice_id.company_id.currency_id:
            price_subtotal_signed = self.invoice_id.currency_id.with_context(date=self.invoice_id._get_currency_rate_date()).compute(price_subtotal_signed, self.invoice_id.company_id.currency_id)
        sign = self.invoice_id.type in ['in_refund', 'out_refund'] and -1 or 1
        self.price_subtotal_signed = price_subtotal_signed * sign
    
    @api.one
    @api.depends('product_id')
    def _compute_mrc_nrc(self):
        if self.product_id.recurring_invoice == True:
            self.nrc_mrc = "MRC"
        else:
            self.nrc_mrc = "NRC"
    
    @api.multi
    def _compute_discount_amount(self):
        for line in self:
            line.discount_amount = line.price_unit * line.quantity - line.price_subtotal
    
    def get_datas(self):
        sub = self.env['account.invoice.line'].search([])
        for records in sub:
            if not records.invoice_line_tax_ids:
                for taxes in records.product_id.taxes_id:
                    if taxes.company_id == records.invoice_id.company_id:
                        records.invoice_line_tax_ids = taxes.ids
    
class StockMove(models.Model):
    _inherit = "stock.move"
    
    @api.multi
    @api.onchange('product_id')
    def product_change(self):
        accounts_data = self.product_id.product_tmpl_id.get_product_accounts()
        if self.location_dest_id.valuation_in_account_id:
            acc_dest = self.location_dest_id.valuation_in_account_id.id
        else:
            acc_dest = accounts_data['stock_output'].id
        self.account_id = acc_dest
        
    @api.multi
    def _get_accounting_data_for_valuation(self):
        """ Return the accounts and journal to use to post Journal Entries for
        the real-time valuation of the quant. """
        self.ensure_one()
        accounts_data = self.product_id.product_tmpl_id.get_product_accounts()

        if self.location_id.valuation_out_account_id:
            acc_src = self.location_id.valuation_out_account_id.id
        else:
            acc_src = accounts_data['stock_input'].id

        if self.account_id:
            acc_dest = self.account_id.id
        elif self.location_dest_id.valuation_in_account_id:
            acc_dest = self.location_dest_id.valuation_in_account_id.id
        else:
            acc_dest = accounts_data['stock_output'].id

        acc_valuation = accounts_data.get('stock_valuation', False)
        if acc_valuation:
            acc_valuation = acc_valuation.id
        if not accounts_data.get('stock_journal', False):
            raise UserError(_('You don\'t have any stock journal defined on your product category, check if you have installed a chart of accounts'))
        if not acc_src:
            raise UserError(_('Cannot find a stock input account for the product %s. You must define one on the product category, or on the location, before processing this operation.') % (self.product_id.name))
        if not acc_dest:
            raise UserError(_('Cannot find a stock output account for the product %s. You must define one on the product category, or on the location, before processing this operation.') % (self.product_id.name))
        if not acc_valuation:
            raise UserError(_('You don\'t have any stock valuation account defined on your product category. You must define one before processing this operation.'))
        journal_id = accounts_data['stock_journal'].id
        return journal_id, acc_src, acc_dest, acc_valuation
    
#     @api.model
#     def _get_account_id(self):
#         accounts_data = self.product_id.product_tmpl_id.get_product_accounts()
#         print(accounts_data) 
#         if self.location_dest_id.valuation_in_account_id:
#             acc_dest = self.location_dest_id.valuation_in_account_id.id
#         else:
#             acc_dest = accounts_data['stock_output'].id
#         return acc_dest
        
    
    account_id = fields.Many2one('account.account', string='Account', index=True, ondelete='cascade')
    internal_transfer = fields.Boolean('Internal Transfer?', related='picking_id.internal_transfer', readonly=1, track_visibility='onchange')

class MrpBom(models.Model):
    _inherit = "mrp.bom"

    def create_netfinity_boms(self):
        boms = self.env['mrp.bom'].search([('company_id', '=', 3)])
        for bom in boms:
            order_lines = []
            for line in bom.bom_line_ids:
                order_lines.append((0, 0, {
                    'product_id': line.product_id.id,
                    'product_qty': line.product_qty,
                    'product_uom_id':line.product_uom_id.id,
                }))

            vals= {
                'product_tmpl_id': bom.product_tmpl_id.id,
                'company_id': 6,
                'product_id': bom.product_id.id,
                'product_qty': bom.product_qty,
                'code': bom.code,
                'type': bom.type,
                'ready_to_produce': bom.ready_to_produce,
                'sequence': bom.sequence,
                'bom_line_ids': order_lines,
                'product_uom_id':bom.product_uom_id.id,
                }
            model2_obj= self.env['mrp.bom']
            model2_obj.create(vals)

class SalesPersons(models.Model):
    _name = 'sales.persons'
    _description = "Sales Persons"
    _order = "percentage DESC"
    
    #@api.model
    #def _get_default_order_id(self):
    #    ctx = self._context
    #    if ctx.get('active_model') == 'sale.order':
    #        return self.env['sale.order'].browse(ctx.get('active_ids')[0]).id
    
    #def _default_percent(self):
    #    ctx = self._context
    #    if ctx.get('model') == 'sale.order':
    #        num = self.env['sale.order'].browse(ctx.get('sales_percentage')[0])
    #        print('sales per', num)
    
    def _default_user_id(self): # this method is to search the hr.employee and return the user id of the person clicking the form atm
        self.env['res.users'].search([('id','=',self.env.uid)])
        return self.env['res.users'].search([('id','=',self.env.uid)])
    
    user_id = fields.Many2one('res.users', string='Sales Person', default=_default_user_id)
    percentage = fields.Float(string='Percentage (%)')
    order_id = fields.Many2one('sale.order', string='Order Reference', required=True, ondelete='cascade', index=True, copy=False)
    main_salesperson = fields.Boolean(string='Main')
    amount = fields.Float(string='Amount', compute='_compute_amount', readonly=False, store=True)
    
    @api.one
    @api.depends('order_id.sales_percentage')
    def _compute_amount(self):
        for line in self:
            line.amount = 100 - self.order_id.sales_percentage

class SaleOrder(models.Model):
    _name = "sale.order"
    _inherit = ['sale.order']
    _description = "Quotation"
    
    @api.model
    def create(self, vals):
        result = super(SaleOrder, self).create(vals)
        result._create_default_salesperson()
        return result
    
    def _prepare_subscription_data(self, template):
        """Prepare a dictionnary of values to create a subscription from a template."""
        self.ensure_one()
        values = {
            'name': template.name,
            'state': 'draft',
            'template_id': template.id,
            'partner_id': self.partner_id.id,
            'user_id': self.user_id.id,
            'date_start': fields.Date.today(),
            'description': self.note or template.description,
            'pricelist_id': self.pricelist_id.id,
            'company_id': self.company_id.id,
            'analytic_account_id': self.analytic_account_id.id,
            'payment_token_id': self.payment_tx_id.payment_token_id.id if template.payment_mandatory else False
        }
        # compute the next date
        today = datetime.date.today()
        periods = {'daily': 'days', 'weekly': 'weeks', 'monthly': 'months', 'yearly': 'years'}
        invoicing_period = relativedelta(**{periods[template.recurring_rule_type]: template.recurring_interval})
        recurring_next_date = today + invoicing_period
        values['recurring_next_date'] = fields.Date.to_string(recurring_next_date)
        return values
    
    @api.depends('order_line.price_total')
    def _amount_all(self):
        """
        Compute the total amounts of the SO.
        """
        for order in self:
            amount_untaxed = amount_tax = amount_nrc = amount_mrc = report_amount_mrc = report_amount_nrc = 0.0
            for line in order.order_line:
                if line.nrc_mrc == "MRC":
                    amount_mrc += line.price_subtotal
                else:
                    amount_nrc += line.price_subtotal
                if line.report_nrc_mrc == "MRC":
                    report_amount_mrc += line.reports_price_subtotal
                else:
                    report_amount_nrc += line.reports_price_subtotal
                amount_untaxed += line.price_subtotal
                amount_tax += line.price_tax
            order.update({
                'amount_untaxed': order.pricelist_id.currency_id.round(amount_untaxed),
                'amount_mrc': order.pricelist_id.currency_id.round(amount_mrc),
                'report_amount_mrc': order.pricelist_id.currency_id.round(report_amount_mrc),
                'report_amount_nrc': order.pricelist_id.currency_id.round(report_amount_nrc),
                'amount_nrc': order.pricelist_id.currency_id.round(amount_nrc),
                'amount_tax': order.pricelist_id.currency_id.round(amount_tax),
                'amount_total': amount_untaxed + amount_tax,
            })
                   
    @api.multi
    def action_cancel(self):
        self.write({'state': 'cancel','bill_confirm':False})
        for line in self.order_line:
            line.confirmed_reports_price_subtotal = 0
            self._unlink_report_lines()
        return self.write({'state': 'cancel','bill_confirm':False})
    
    @api.multi
    def copy_data(self, default=None):
        if default is None:
            default = {}
        if 'order_line' not in default:
            default['order_line'] = [(0, 0, line.copy_data()[0]) for line in self.order_line.filtered(lambda l: not l.is_downpayment)]
        return super(SaleOrder, self).copy_data(default)
    
    @api.depends('report_amount_mrc','state')
    def check_report_mrc(self):
        if self.report_amount_mrc < 0 and self.state in ['sent','sale','done']:
            print(self.report_amount_mrc, 'it works bro')
            for line in self.order_line:
                    line.negative_reports_price_subtotal = line.reports_price_subtotal
                    line.reports_price_subtotal = 0
                    line.confirmed_reports_price_subtotal = line.reports_price_subtotal
        else:
            for line in self.order_line:
                line.confirmed_reports_price_subtotal = line.reports_price_subtotal
    
    @api.multi
    def action_confirm(self):
        res = super(SaleOrder, self).action_confirm()
        self.check_report_mrc()
        self._create_default_salesperson()
        self._prepare_report_lines()
        return res
    
    @api.multi
    def billing_confirm(self):
        for order in self:
            order.write({'bill_confirm': True})
        return True

    confirmation_date = fields.Datetime(string='Confirmation Date', readonly=False, index=True, help="Date on which the sales order is confirmed.", oldname="date_confirm", copy=False)
    
    remarks = fields.Char('Remarks', track_visibility='onchange')
    date_order = fields.Date(string='Order Date', required=True, readonly=True, index=True, states={'draft': [('readonly', False)], 'sent': [('readonly', False)]}, copy=False, default=fields.Datetime.now)
    period = fields.Integer('Service Contract Period (in months)', default="1", required=True, track_visibility='onchange')
    amount_nrc = fields.Monetary(string='Total NRC', store=True, readonly=True, compute='_amount_all', track_visibility='onchange')
    amount_mrc = fields.Monetary(string='Total MRC', store=True, readonly=True, compute='_amount_all', track_visibility='onchange')
    bill_confirm = fields.Boolean('Billing Confirmation', track_visibility='onchange', copy=False,)
    account_executive_id = fields.Many2one(string='Account Executive', comodel_name='hr.employee')
    account_manager_id = fields.Char(string='Account Manager')
    upsell_sub = fields.Boolean('Upsell?', track_visibility='onchange', copy=False, store=True)
    report_amount_mrc = fields.Monetary(string='Report Total MRC', store=False, readonly=True, compute='_amount_all', track_visibility='onchange')
    report_amount_nrc = fields.Monetary(string='Report Total NRC', store=False, readonly=True, compute='_amount_all', track_visibility='onchange')
    
    crm_tag_ids = fields.Many2many('crm.lead.tag', string='Tags', help="Classify and analyze your sales categories like: Training, Service")
    
    sales_persons_ids = fields.One2many('sales.persons', 'order_id', string='Sales Persons')
    
    report_sale_order_line_ids = fields.One2many('report.sale.order.line', 'order_id', string='Report Sale Order Line')
    
    sales_percentage = fields.Float(string='Percentage', store=False, readonly=True, compute='_compute_salepersons_percentages', track_visibility='onchange')
    
    @api.one
    def _prepare_report_lines(self):
        self.ensure_one()
        for person in self.sales_persons_ids:
            for line in self.order_line:
                self.report_sale_order_line_ids.create({
                     'type': line.type,
                     'order_id': self.id,
                     'type': line.type,
                     'nrc_mrc': line.nrc_mrc,
                     'name': line.name,
                     'sub_account_id': line.sub_account_id.id,
                     'product_id': line.product_id.id,
                     'account_id': line.account_id.id,
                     'product_uom_qty': line.product_uom_qty * person.percentage/100,
                     'product_uom': line.product_uom.id,
                     'price_unit': line.price_unit,
                     'tax_id': [(6, 0, line.tax_id.ids)],
                     'discount': line.discount,
                     'sales_person_id': person.user_id.id,
                     'report_price_subtotal': line.reports_price_subtotal * person.percentage/100,
                     'new_sub': line.new_sub,
                     'report_nrc_mrc': line.report_nrc_mrc,
                })
    
    @api.multi
    def _unlink_report_lines(self):
        for lines in self.report_sale_order_line_ids:
            lines.unlink()
    
    @api.one
    def _create_default_salesperson(self):
        self.ensure_one()
        if not self.sales_persons_ids:
            for line in self:
                line.sales_persons_ids.create({
                     #'user_id': self.env.uid,
                     'user_id': self.user_id.id,
                     'order_id': self.id,
                     'main_salesperson': True,
                     'percentage': 100,
                })
    
    @api.one
    @api.depends('sales_persons_ids.percentage', 'sales_percentage')
    def _compute_salepersons_percentages(self):
        self.ensure_one()
        for line in self.sales_persons_ids:
            self.sales_percentage += line.percentage
    
    @api.onchange('partner_id')
    def _partner_id(self):
        self.user_id = self.partner_id.user_id
    
    @api.onchange('sales_percentage')
    def _onchange_precentage(self):
        if self.sales_percentage > 100.00:
            raise UserError(_('This is Above 100% .'))
    
    @api.multi
    def create_report_lines(self):
        self._create_default_salesperson()
        self._prepare_report_lines()
        
    @api.multi
    def get_account_lines(self):
        for line in self.order_line:
            if not line.account_id:
                line.default_account_id()
        self.get_report_account_lines()
    
    @api.multi
    def get_report_account_lines(self):
        for line in self.report_sale_order_line_ids:
            if not line.account_id:
                line.default_account_id()
    
class SaleOrderLine(models.Model):
    _name = 'sale.order.line'
    _description = 'Sales Order Line'
    _inherit = ['sale.order.line']
    
    type = fields.Selection([('sale', 'Sale'), ('lease', 'Lease')], string='Type', required=True,default='sale')
    nrc_mrc = fields.Char('MRC/NRC', compute='_compute_mrc_nrc', readonly=True, store=True)
    sub_account_id = fields.Many2one('sub.account', string='Child Account', index=True, ondelete='cascade', store=True)
    
    report_nrc_mrc = fields.Char('Report MRC/NRC', compute='_compute_report_mrc_nrc', readonly=True, store=True)
    reports_price_subtotal = fields.Float('Report Subtotal', readonly=False, compute='_compute_report_subtotal', store=True)
    report_date = fields.Date('Report Date', readonly=False, compute='_compute_report_date', store=True)
    new_sub = fields.Boolean('New?', track_visibility='onchange', copy=False)

    negative_reports_price_subtotal = fields.Float('Negative Report Subtotal', readonly=True, store=True)

    confirmed_reports_price_subtotal = fields.Float('Confirmed Report Subtotal', compute='_compute_report_subtotal', readonly=True, store=True)
    
    price_review_date = fields.Date(string='Price Review Date', readonly=True, related='sub_account_id.price_review_date', store=True)
    
    account_id = fields.Many2one('account.account', string='Account',
        required=False, states={'draft': [('readonly', False)]},
        domain=[('deprecated', '=', False)], help="The account used for this sale.")
    
    @api.onchange('product_id')
    def default_account_id(self):
        if self.product_id.property_account_income_id:
            self.account_id = self.product_id.property_account_income_id
        elif self.product_id.categ_id.property_account_income_categ_id:
            self.account_id = self.product_id.categ_id.property_account_income_categ_id
    
    @api.one
    @api.depends('report_nrc_mrc')
    def _compute_report_subtotal(self):
        report_price_subtotal = 0.0
        upsell_report_price_subtotal = 0.0
        sub = self.env['sale.subscription.line'].search([('analytic_account_id.state','=','open'), ('sub_account_id.parent_id', '=', self.order_id.partner_id.id), ('sub_account_id', '=', self.sub_account_id.id), ('product_id', '=', self.product_id.id)], limit=1)
        for line in self:
            if line.order_id.state in ['sale','done']:
                line.confirmed_reports_price_subtotal = line.reports_price_subtotal 
            else:
                if line.report_nrc_mrc == "MRC":
                    if sub:
                        line.write({'new_sub': False})
                        upsell_report_price_subtotal = line.price_subtotal - sub.price_subtotal / sub.analytic_account_id.template_id.recurring_interval
                        #if upsell_report_price_subtotal < 0:
                        #    line.reports_price_subtotal = 0
                        #else:
                        line.reports_price_subtotal = upsell_report_price_subtotal
                    else:
                        line.write({'new_sub': True})
                        line.reports_price_subtotal = line.price_subtotal
                else:
                    if sub:
                        if line.report_nrc_mrc == "NRC":
                            report_price_subtotal = line.price_subtotal/100 * 20
                            line.reports_price_subtotal = report_price_subtotal
                        else:
                            line.reports_price_subtotal = line.price_subtotal
                    else:
                        line.write({'new_sub': True})
                        if line.report_nrc_mrc == "NRC":
                            report_price_subtotal = line.price_subtotal/100 * 20
                            line.reports_price_subtotal = report_price_subtotal
                        else:
                            line.reports_price_subtotal = line.price_subtotal
    
    
    @api.one
    @api.depends('report_nrc_mrc', 'new_sub', 'order_id.confirmation_date', 'sub_account_id.perm_up_date', 'sub_account_id.activation_date')
    def _compute_report_date(self):
        for line in self:
            if line.report_nrc_mrc == "NRC":
                line.report_date = line.order_id.confirmation_date
            else:
                if line.report_nrc_mrc == "MRC":
                    if line.new_sub == True:
                        line.report_date = line.sub_account_id.activation_date
                    else:
                        line.report_date = line.sub_account_id.perm_up_date
    
    @api.multi
    def _prepare_invoice_line(self, qty):
        """
        Prepare the dict of values to create the new invoice line for a sales order line.
        :param qty: float quantity to invoice
        """
        self.ensure_one()
        res = {}
        account = self.product_id.property_account_income_id or self.product_id.categ_id.property_account_income_categ_id
        if not account:
            raise UserError(_('Please define income account for this product: "%s" (id:%d) - or for its category: "%s".') %
                (self.product_id.name, self.product_id.id, self.product_id.categ_id.name))

        fpos = self.order_id.fiscal_position_id or self.order_id.partner_id.property_account_position_id
        if fpos:
            account = fpos.map_account(account)

        res = {
            'name': self.name,
            'sequence': self.sequence,
            'origin': self.order_id.name,
            'sub_account_id' : self.sub_account_id.id,
            'account_id': account.id,
            'price_unit': self.price_unit,
            'quantity': qty,
            'discount': self.discount,
            'uom_id': self.product_uom.id,
            'product_id': self.product_id.id or False,
            'layout_category_id': self.layout_category_id and self.layout_category_id.id or False,
            'invoice_line_tax_ids': [(6, 0, self.tax_id.ids)],
            'account_analytic_id': self.order_id.analytic_account_id.id,
            'analytic_tag_ids': [(6, 0, self.analytic_tag_ids.ids)],
        }
        return res
    
    def _prepare_subscription_line_data(self):
        """Prepare a dictionnary of values to add lines to a subscription."""
        values = list()
        for line in self:
            values.append((0, False, {
                'sub_account_id' : line.sub_account_id.id,
                'product_id': line.product_id.id,
                'name': line.name,
                'quantity': line.product_uom_qty,
                'uom_id': line.product_uom.id,
                'price_unit': line.price_unit,
                'discount': line.discount if line.order_id.subscription_management != 'upsell' else False,
            }))
        return values
    
    @api.one
    @api.depends('product_id')
    def _compute_mrc_nrc(self):
        if self.product_id.recurring_invoice == True:
            self.nrc_mrc = "MRC"
        else:
            self.nrc_mrc = "NRC"
            
            
    @api.one
    @api.depends('order_id.period')
    def _compute_report_mrc_nrc(self):
        if self.nrc_mrc == "MRC":
            if self.order_id.period < 12:
                self.report_nrc_mrc = "NRC"
            else:
                self.report_nrc_mrc = "MRC"
        else:
            self.report_nrc_mrc = "NRC"
        
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

        #name = product.name_get()[0][1]
        name = product.name
        if product.description_sale:
            name += '\n' + product.description_sale
        vals['name'] = name

        self._compute_tax_id()

        if self.order_id.pricelist_id and self.order_id.partner_id:
            vals['price_unit'] = self.env['account.tax']._fix_tax_included_price_company(self._get_display_price(product), product.taxes_id, self.tax_id, self.company_id)
        if self.type == "lease":
            lease_price = self.product_id.lease_price
            currency_id = 124
            if currency_id != self.order_id.pricelist_id.currency_id.id:
                context_partner = dict(self.env.context, partner_id=self.order_id.partner_id.id, date=self.order_id.date_order)
                vals['price_unit'] = self.env['res.currency'].browse(currency_id).with_context(context_partner).compute(lease_price, self.order_id.pricelist_id.currency_id)
            else:
                vals['price_unit'] = lease_price
            
        self.update(vals)

        return result
    
    @api.onchange('product_uom', 'product_uom_qty')
    def product_uom_change(self):
        if not self.product_uom or not self.product_id:
            self.price_unit = 0.0
            return
        if self.order_id.pricelist_id and self.order_id.partner_id:
            product = self.product_id.with_context(
                lang=self.order_id.partner_id.lang,
                partner=self.order_id.partner_id.id,
                quantity=self.product_uom_qty,
                date=self.order_id.date_order,
                pricelist=self.order_id.pricelist_id.id,
                uom=self.product_uom.id,
                fiscal_position=self.env.context.get('fiscal_position')
            )
            if self.type == "lease":
                lease_price = self.product_id.lease_price
                currency_id = 124
                if currency_id != self.order_id.pricelist_id.currency_id.id:
                    context_partner = dict(self.env.context, partner_id=self.order_id.partner_id.id, date=self.order_id.date_order)
                    self.price_unit = self.env['res.currency'].browse(currency_id).with_context(context_partner).compute(lease_price, self.order_id.pricelist_id.currency_id)
                else:
                    self.price_unit = lease_price
            else:
                self.price_unit = self.env['account.tax']._fix_tax_included_price_company(self._get_display_price(product), product.taxes_id, self.tax_id, self.company_id)
                
class ReportSaleOrderLine(models.Model):
    _name = 'report.sale.order.line'
    _description = 'Report Sales Order Line'
    _inherit = ['sale.order.line']
    
    sales_person_id = fields.Many2one('res.users', string='Sales Person')
    report_price_subtotal = fields.Float('Report Subtotal')
    
    confirmed_reports_price_subtotal = fields.Float('Confirmed Report Subtotal', readonly=True, store=True)
    
    qty_delivered_updateable = fields.Boolean(compute='_compute_qty_delivered_updateable', string='Can Edit Delivered', readonly=True, default=True)
    
    @api.depends('product_id.invoice_policy', 'order_id.state')
    def _compute_qty_delivered_updateable(self):
        for line in self:
            line.qty_delivered_updateable = (line.order_id.state == 'sale') and (line.product_id.service_type == 'manual') and (line.product_id.expense_policy == 'no')
    
    @api.onchange('product_id')
    def default_account_id(self):
        if self.product_id.property_account_income_id:
            self.account_id = self.product_id.property_account_income_id
        elif self.product_id.categ_id.property_account_income_categ_id:
            self.account_id = self.product_id.categ_id.property_account_income_categ_id
    
class AccountReconcileModel(models.Model):
    _name = "account.reconcile.model"
    _inherit = "account.reconcile.model"
    
    def _default_analytic(self):
        return self.env['account.analytic.account'].search([('name','=','Netcom')])
    
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account', default=_default_analytic, ondelete='set null')  

class BudgetDept(models.Model):
    _name = 'account.budget.post'
    _inherit = 'account.budget.post'
    
    department_id = fields.Many2one(
        comodel_name="hr.department",
        string='Department')
    
class SaleSubscription(models.Model):
    _inherit = "sale.subscription"

    @api.multi
    def _prepare_invoice_line(self, line, fiscal_position):
        res = super(SaleSubscription, self)._prepare_invoice_line(line, fiscal_position)
        default_analytic_account = self.env['account.analytic.default'].account_get(line.product_id.id, self.partner_id.id, self.user_id.id, fields.Date.today())
        if default_analytic_account:
            res.update({'account_analytic_id': default_analytic_account.analytic_id.id})
        return res
    
  
    
class HrPayslipWorkedDays(models.Model):
    _inherit = 'hr.payslip.worked_days'

    name = fields.Char(string='Description', required=False)
    code = fields.Char(required=False, help="The code that can be used in the salary rules")
    
    
    
class SaleSubscriptionWizard(models.TransientModel):
    _name = 'sale.subscription.wizard'
    _inherit = 'sale.subscription.wizard'
    
    
    @api.multi
    def create_sale_order(self):
        fpos_id = self.env['account.fiscal.position'].get_fiscal_position(self.subscription_id.partner_id.id)
        sale_order_obj = self.env['sale.order']
        team = self.env['crm.team']._get_default_team_id(user_id=self.subscription_id.user_id.id)
        order = sale_order_obj.create({
            'partner_id': self.subscription_id.partner_id.id,
            'analytic_account_id': self.subscription_id.analytic_account_id.id,
            'team_id': team and team.id,
            'pricelist_id': self.subscription_id.pricelist_id.id,
            'fiscal_position_id': fpos_id,
            'subscription_management': 'upsell',
#           'upsell_sub': True,
        })
        for line in self.option_lines:
            self.subscription_id.partial_invoice_line(order, line, date_from=self.date_from)
        order.order_line._compute_tax_id()
        return {
            "type": "ir.actions.act_window",
            "res_model": "sale.order",
            "views": [[False, "form"]],
            "res_id": order.id,
        }
    
    
class BDDSaleReport(models.Model):
    _name = "netcom.sale.report"
    _inherit = "sale.report"
    _description = "Netcom BDD Sales Orders Report"
    _auto = False
    _rec_name = 'date'
    _order = 'date desc'

    name = fields.Char('Order Reference', readonly=True)
    date = fields.Datetime('Date Order', readonly=True)
    confirmation_date = fields.Datetime('Confirmation Date', readonly=True)
    product_id = fields.Many2one('product.product', 'Product', readonly=True)
    sub_account_id = fields.Many2one('sub.account', 'Sub Account', readonly=True)
    product_uom = fields.Many2one('product.uom', 'Unit of Measure', readonly=True)
    product_uom_qty = fields.Float('Qty Ordered', readonly=True)
    qty_delivered = fields.Float('Qty Delivered', readonly=True)
    qty_to_invoice = fields.Float('Qty To Invoice', readonly=True)
    qty_invoiced = fields.Float('Qty Invoiced', readonly=True)
    partner_id = fields.Many2one('res.partner', 'Partner', readonly=True)
    company_id = fields.Many2one('res.company', 'Company', readonly=True)
    user_id = fields.Many2one('res.users', 'Salesperson', readonly=True)
    price_total = fields.Float('Total', readonly=True)
    price_subtotal = fields.Float('Untaxed Total', readonly=True)
    amt_to_invoice = fields.Float('Amount To Invoice', readonly=True)
    amt_invoiced = fields.Float('Amount Invoiced', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', 'Product Template', readonly=True)
    categ_id = fields.Many2one('product.category', 'Product Category', readonly=True)
    nbr = fields.Integer('# of Lines', readonly=True)
    pricelist_id = fields.Many2one('product.pricelist', 'Pricelist', readonly=True)
    analytic_account_id = fields.Many2one('account.analytic.account', 'Analytic Account', readonly=True)
    team_id = fields.Many2one('crm.team', 'Sales Channel', readonly=True, oldname='section_id')
    country_id = fields.Many2one('res.country', 'Partner Country', readonly=True)
    commercial_partner_id = fields.Many2one('res.partner', 'Commercial Entity', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft Quotation'),
        ('sent', 'Quotation Sent'),
        ('sale', 'Sales Order'),
        ('done', 'Sales Done'),
        ('cancel', 'Cancelled'),
        ], string='Status', readonly=True)
    weight = fields.Float('Gross Weight', readonly=True)
    volume = fields.Float('Volume', readonly=True)
    
    report_nrc_mrc = fields.Char('Report MRC/NRC', readonly=True)
    reports_price_subtotal = fields.Float('Report Subtotal (SALE)', readonly=True)    
    report_date = fields.Date('Report Date', readonly=True)
    sales_target = fields.Float(string='Salesperson Target', readonly=True)
    confirmed_reports_price_subtotal = fields.Float('Confirmed Report Subtotal', readonly=True)
    price_review_date = fields.Date(string='Price Review Date', readonly=True)
    #upsell_sub = fields.Boolean('Upsell', readonly=True)
    
    
    def _select(self):
        select_str = """
            WITH currency_rate as (%s)
             SELECT min(l.id) as id,
                    l.product_id as product_id,
                    l.sub_account_id as sub_account_id,
                    l.price_review_date as price_review_date,
                    l.report_nrc_mrc as report_nrc_mrc,
                    l.report_date as report_date,
                    t.uom_id as product_uom,
                    sum(l.product_uom_qty / u.factor * u2.factor) as product_uom_qty,
                    sum(l.qty_delivered / u.factor * u2.factor) as qty_delivered,
                    sum(l.qty_invoiced / u.factor * u2.factor) as qty_invoiced,
                    sum(l.qty_to_invoice / u.factor * u2.factor) as qty_to_invoice,
                    sum(l.price_total / COALESCE(cr.rate, 1.0)) as price_total,
                    sum(l.price_subtotal / COALESCE(cr.rate, 1.0)) as price_subtotal,
                    sum(l.reports_price_subtotal / COALESCE(cr.rate, 1.0)) as reports_price_subtotal,
                    sum(l.confirmed_reports_price_subtotal / COALESCE(cr.rate, 1.0)) as confirmed_reports_price_subtotal,
                    sum(l.amt_to_invoice / COALESCE(cr.rate, 1.0)) as amt_to_invoice,
                    sum(l.amt_invoiced / COALESCE(cr.rate, 1.0)) as amt_invoiced,
                    count(*) as nbr,
                    s.name as name,
                    s.date_order as date,
                    s.confirmation_date as confirmation_date,
                    s.state as state,
                    s.partner_id as partner_id,
                    s.user_id as user_id,
                    s.company_id as company_id,
                    extract(epoch from avg(date_trunc('day',s.date_order)-date_trunc('day',s.create_date)))/(24*60*60)::decimal(16,2) as delay,
                    t.categ_id as categ_id,
                    s.pricelist_id as pricelist_id,
                    s.analytic_account_id as analytic_account_id,
                    s.team_id as team_id,
                    p.product_tmpl_id,
                    users.sales_target as sales_target,
                    partner.country_id as country_id,
                    partner.commercial_partner_id as commercial_partner_id,
                    sum(p.weight * l.product_uom_qty / u.factor * u2.factor) as weight,
                    sum(p.volume * l.product_uom_qty / u.factor * u2.factor) as volume
        """ % self.env['res.currency']._select_companies_rates()
        return select_str

    def _from(self):
        from_str = """
                sale_order_line l
                      join sale_order s on (l.order_id=s.id)
                      join res_users users on s.user_id = users.id
                      join res_partner partner on s.partner_id = partner.id
                        left join product_product p on (l.product_id=p.id)
                            left join product_template t on (p.product_tmpl_id=t.id)
                    left join product_uom u on (u.id=l.product_uom)
                    left join product_uom u2 on (u2.id=t.uom_id)
                    left join product_pricelist pp on (s.pricelist_id = pp.id)
                    left join currency_rate cr on (cr.currency_id = pp.currency_id and
                        cr.company_id = s.company_id and
                        cr.date_start <= coalesce(s.date_order, now()) and
                        (cr.date_end is null or cr.date_end > coalesce(s.date_order, now())))
        """
        return from_str

    def _group_by(self):
        group_by_str = """
            GROUP BY l.product_id,
                    l.order_id,
                    l.sub_account_id,
                    t.uom_id,
                    t.categ_id,
                    s.name,
                    s.date_order,
                    s.confirmation_date,
                    s.partner_id,
                    s.user_id,
                    s.state,
                    l.report_nrc_mrc,
                    l.report_date,
                    l.price_review_date,
                    s.company_id,
                    s.pricelist_id,
                    s.analytic_account_id,
                    s.team_id,
                    p.product_tmpl_id,
                    users.sales_target,
                    partner.country_id,
                    partner.commercial_partner_id
        """
        return group_by_str

    @api.model_cr
    def init(self):
        # self._table = sale_report
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""CREATE or REPLACE VIEW %s as (
            %s
            FROM ( %s )
            %s
            )""" % (self._table, self._select(), self._from(), self._group_by()))
        

class BDDSalesPersonReport(models.Model):
    _name = "netcom.sales.person.report"
    _inherit = "netcom.sale.report"
    _description = "Netcom BDD Sales Persons Order Report"
    _auto = False
    _rec_name = 'date'
    _order = 'date desc'

    name = fields.Char('Order Reference', readonly=True)
    date = fields.Datetime('Date Order', readonly=True)
    confirmation_date = fields.Datetime('Confirmation Date', readonly=True)
    product_id = fields.Many2one('product.product', 'Product', readonly=True)
    sub_account_id = fields.Many2one('sub.account', 'Sub Account', readonly=True)
    account_id = fields.Many2one('account.account', 'Account', readonly=True)
    product_uom = fields.Many2one('product.uom', 'Unit of Measure', readonly=True)
    product_uom_qty = fields.Float('Qty Ordered', readonly=True)
    qty_delivered = fields.Float('Qty Delivered', readonly=True)
    qty_to_invoice = fields.Float('Qty To Invoice', readonly=True)
    qty_invoiced = fields.Float('Qty Invoiced', readonly=True)
    partner_id = fields.Many2one('res.partner', 'Partner', readonly=True)
    company_id = fields.Many2one('res.company', 'Company', readonly=True)
    user_id = fields.Many2one('res.users', 'Main Salesperson', readonly=True)
    sales_person_id = fields.Many2one('res.users', 'Salesperson', readonly=True)
    price_total = fields.Float('Total', readonly=True)
    price_subtotal = fields.Float('Untaxed Total', readonly=True)
    amt_to_invoice = fields.Float('Amount To Invoice', readonly=True)
    amt_invoiced = fields.Float('Amount Invoiced', readonly=True)
    product_tmpl_id = fields.Many2one('product.template', 'Product Template', readonly=True)
    categ_id = fields.Many2one('product.category', 'Product Category', readonly=True)
    nbr = fields.Integer('# of Lines', readonly=True)
    pricelist_id = fields.Many2one('product.pricelist', 'Pricelist', readonly=True)
    analytic_account_id = fields.Many2one('account.analytic.account', 'Analytic Account', readonly=True)
    team_id = fields.Many2one('crm.team', 'Sales Channel', readonly=True, oldname='section_id')
    country_id = fields.Many2one('res.country', 'Partner Country', readonly=True)
    commercial_partner_id = fields.Many2one('res.partner', 'Commercial Entity', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft Quotation'),
        ('sent', 'Quotation Sent'),
        ('sale', 'Sales Order'),
        ('done', 'Sales Done'),
        ('cancel', 'Cancelled'),
        ], string='Status', readonly=True)
    weight = fields.Float('Gross Weight', readonly=True)
    volume = fields.Float('Volume', readonly=True)
    
    report_nrc_mrc = fields.Char('Report MRC/NRC', readonly=True)
    report_price_subtotal = fields.Float('Report Subtotal (SALE)', readonly=True)    
    report_date = fields.Date('Report Date', readonly=True)
    sales_target = fields.Float(string='Salesperson Target', readonly=True)
    confirmed_reports_price_subtotal = fields.Float('Confirmed Report Subtotal', readonly=True)
    price_review_date = fields.Date(string='Price Review Date', readonly=True)
    #upsell_sub = fields.Boolean('Upsell', readonly=True)
    
    
    def _select(self):
        select_str = """
            WITH currency_rate as (%s)
             SELECT min(l.id) as id,
                    l.product_id as product_id,
                    l.sub_account_id as sub_account_id,
                    l.account_id as account_id,
                    l.price_review_date as price_review_date,
                    l.report_nrc_mrc as report_nrc_mrc,
                    l.report_date as report_date,
                    t.uom_id as product_uom,
                    sum(l.product_uom_qty / u.factor * u2.factor) as product_uom_qty,
                    sum(l.qty_delivered / u.factor * u2.factor) as qty_delivered,
                    sum(l.qty_invoiced / u.factor * u2.factor) as qty_invoiced,
                    sum(l.qty_to_invoice / u.factor * u2.factor) as qty_to_invoice,
                    sum(l.price_total / COALESCE(cr.rate, 1.0)) as price_total,
                    sum(l.price_subtotal / COALESCE(cr.rate, 1.0)) as price_subtotal,
                    sum(l.report_price_subtotal / COALESCE(cr.rate, 1.0)) as report_price_subtotal,
                    sum(l.confirmed_reports_price_subtotal / COALESCE(cr.rate, 1.0)) as confirmed_reports_price_subtotal,
                    sum(l.amt_to_invoice / COALESCE(cr.rate, 1.0)) as amt_to_invoice,
                    sum(l.amt_invoiced / COALESCE(cr.rate, 1.0)) as amt_invoiced,
                    count(*) as nbr,
                    s.name as name,
                    s.date_order as date,
                    s.confirmation_date as confirmation_date,
                    s.state as state,
                    s.partner_id as partner_id,
                    s.user_id as user_id,
                    l.sales_person_id as sales_person_id,
                    s.company_id as company_id,
                    extract(epoch from avg(date_trunc('day',s.date_order)-date_trunc('day',s.create_date)))/(24*60*60)::decimal(16,2) as delay,
                    t.categ_id as categ_id,
                    s.pricelist_id as pricelist_id,
                    s.analytic_account_id as analytic_account_id,
                    s.team_id as team_id,
                    p.product_tmpl_id,
                    users.sales_target as sales_target,
                    partner.country_id as country_id,
                    partner.commercial_partner_id as commercial_partner_id,
                    sum(p.weight * l.product_uom_qty / u.factor * u2.factor) as weight,
                    sum(p.volume * l.product_uom_qty / u.factor * u2.factor) as volume
        """ % self.env['res.currency']._select_companies_rates()
        return select_str

    def _from(self):
        from_str = """
                report_sale_order_line l
                      join sale_order s on (l.order_id=s.id)
                      join res_users users on l.sales_person_id = users.id
                      join res_partner partner on s.partner_id = partner.id
                        left join product_product p on (l.product_id=p.id)
                            left join product_template t on (p.product_tmpl_id=t.id)
                    left join product_uom u on (u.id=l.product_uom)
                    left join product_uom u2 on (u2.id=t.uom_id)
                    left join product_pricelist pp on (s.pricelist_id = pp.id)
                    left join currency_rate cr on (cr.currency_id = pp.currency_id and
                        cr.company_id = s.company_id and
                        cr.date_start <= coalesce(s.date_order, now()) and
                        (cr.date_end is null or cr.date_end > coalesce(s.date_order, now())))
        """
        return from_str

    def _group_by(self):
        group_by_str = """
            GROUP BY l.product_id,
                    l.order_id,
                    l.sub_account_id,
                    l.account_id,
                    t.uom_id,
                    t.categ_id,
                    s.name,
                    s.date_order,
                    s.confirmation_date,
                    s.partner_id,
                    s.user_id,
                    l.sales_person_id,
                    s.state,
                    l.report_nrc_mrc,
                    l.report_date,
                    l.price_review_date,
                    s.company_id,
                    s.pricelist_id,
                    s.analytic_account_id,
                    s.team_id,
                    p.product_tmpl_id,
                    users.sales_target,
                    partner.country_id,
                    partner.commercial_partner_id
        """
        return group_by_str

    @api.model_cr
    def init(self):
        # self._table = sale_report
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""CREATE or REPLACE VIEW %s as (
            %s
            FROM ( %s )
            %s
            )""" % (self._table, self._select(), self._from(), self._group_by()))