# -*- coding: utf-8 -*-
import datetime
import uuid
import time
import traceback

from collections import Counter
from dateutil.relativedelta import relativedelta
from datetime import date, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import format_date

from odoo.addons import decimal_precision as dp

#for manufacturing order production
from odoo.tools import float_compare, float_round
from datetime import datetime

class ResCompany(models.Model):
    _inherit = 'res.company'

    netcom_company_bank_ids = fields.One2many(
        comodel_name='netcom.res.company.bank',
        inverse_name='company_id',
        string='Banks'
    )

    invoice_comment = fields.Text(string='Invoice Comment')


class ResCompanyBank(models.Model):
    _name = 'netcom.res.company.bank'
    _description = 'Netcom Banks'

    naira_account = fields.Char(string='Naira Account')
    usd_account = fields.Char(string='USD Account')
    company_id = fields.Many2one(comodel_name='res.company', string='Company', ondelete='cascade')


class Partner(models.Model):
    _name = 'res.partner'
    _inherit = 'res.partner'

    parent_account_number = fields.Char('Parent Account Number', required=False, index=True, copy=False,)
    contact_name = fields.Char('Contact Name')

    @api.model
    def create(self, vals):
#         if vals.get('parent_account_number', 'New') == 'New':
        if 'customer' in vals and vals['customer'] == True:
            vals['parent_account_number'] = self.env['ir.sequence'].next_by_code('res.partner') or '/'
        return super(Partner, self).create(vals)

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
    planned_revenue = fields.Float('Expected Revenue',compute='_compute_planned_revenue', track_visibility='always')
    name = fields.Char('Services', required=True, index=True)
    acc_executive = fields.Many2one('res.users', string='Account Executive', index=True, track_visibility='onchange')
    
    @api.one
    @api.depends('nrc','mrc')    
    def _compute_planned_revenue(self):
        self.planned_revenue = self.nrc + self.mrc
    
    @api.multi    
    def write(self, vals):
        # stage change: update date_last_stage_update
        if 'acc_executive' in vals:
            self.message_subscribe_users(vals['acc_executive'])
            subject = "Oppurtunity {} has been assigned to you".format(self.name)
            body = "Please Create the Quotation"
            partner_ids = self.env['res.users'].search([('id','=',vals['acc_executive'])]).partner_id.id
            self.message_post(subject=subject,body=body,partner_ids=[(4, partner_ids)])
            stage_id = self._stage_find(domain=[('probability', '=', 70.0), ('on_change', '=', True)])
            vals['stage_id'] = stage_id.id
        return super(Lead, self).write(vals)
    
    @api.multi
    def assign_engineer(self):
        channel_id = self.env['ir.model.data'].xmlid_to_object('netcom.channel_all_bom')
        print(channel_id)
        self.message_subscribe(channel_ids=[channel_id.id])
        subject = "Oppurtunity {} has been assigned to Engineering".format(self.name)
        body = "Please Create the Quotation"
#         channel_id.message_post(subject=subject,body=body)
        self.message_post(subject=subject,body=subject,channel_ids=[(4, channel_id.id)])
        stage_id = self._stage_find(domain=[('probability', '=', 75.0), ('on_change', '=', True)])
        self.write({'stage_id': stage_id.id})
        return {}

class SaleSubscription(models.Model):
    _name = "sale.subscription"
    _description = "Sale Subscription"
    _inherit = ['sale.subscription']

    reference_des = fields.Char(string='Reference/Description')
    
    @api.depends('recurring_invoice_line_ids', 'recurring_invoice_line_ids.quantity', 'recurring_invoice_line_ids.price_subtotal', 'template_id')
    def _compute_recurring_total(self):
        for account in self:
            account.recurring_total = sum(line.price_subtotal for line in account.recurring_invoice_line_ids)
    
    def _prepare_invoice_data(self):
        self.ensure_one()

        if not self.partner_id:
            raise UserError(_("You must first select a Customer for Subscription %s!") % self.name)

        if 'force_company' in self.env.context:
            company = self.env['res.company'].browse(self.env.context['force_company'])
        else:
            company = self.company_id
            self = self.with_context(force_company=company.id, company_id=company.id)

        fpos_id = self.env['account.fiscal.position'].get_fiscal_position(self.partner_id.id)
        journal = self.template_id.journal_id or self.env['account.journal'].search([('type', '=', 'sale'), ('company_id', '=', company.id)], limit=1)
        if not journal:
            raise UserError(_('Please define a sale journal for the company "%s".') % (company.name or '', ))

        next_date = fields.Date.from_string(self.recurring_next_date)
        if not next_date:
            raise UserError(_('Please define Date of Next Invoice of "%s".') % (self.display_name,))
        periods = {'daily': 'days', 'weekly': 'weeks', 'monthly': 'months', 'yearly': 'years'}
        end_date = next_date + relativedelta(**{periods[self.recurring_rule_type]: self.recurring_interval})
        end_date = end_date - relativedelta(days=1)     # remove 1 day as normal people thinks in term of inclusive ranges.
        addr = self.partner_id.address_get(['delivery'])

        return {
            'account_id': self.partner_id.property_account_receivable_id.id,
            'interval' : self.template_id.recurring_interval,
            'type': 'out_invoice',
            'date_due' : self.recurring_next_date,
            'partner_id': self.partner_id.id,
            'user_id' : self.user_id.id,
            'partner_shipping_id': addr['delivery'],
            'currency_id': self.pricelist_id.currency_id.id,
            'journal_id': journal.id,
            'origin': self.code,
            'fiscal_position_id': fpos_id,
            'payment_term_id': self.partner_id.property_payment_term_id.id,
            'company_id': company.id,
            'comment': _('''This invoice covers the following period: %s - %s \n%s''') % (format_date(self.env, next_date), format_date(self.env, end_date),company.invoice_comment),
        }
    
    def _prepare_invoice_line(self, line, fiscal_position):
        if 'force_company' in self.env.context:
            company = self.env['res.company'].browse(self.env.context['force_company'])
        else:
            company = line.analytic_account_id.company_id
            line = line.with_context(force_company=company.id, company_id=company.id)

        account = line.product_id.property_account_income_id
        if not account:
            account = line.product_id.categ_id.property_account_income_categ_id
        account_id = fiscal_position.map_account(account).id

        tax = line.product_id.taxes_id.filtered(lambda r: r.company_id == company)
        tax = fiscal_position.map_tax(tax, product=line.product_id, partner=self.partner_id)
        return {
            'name': line.name,
            'account_id': account_id,
            'account_analytic_id': line.analytic_account_id.analytic_account_id.id,
            'subscription_id': line.analytic_account_id.id,
            'price_unit': line.price_unit or 0.0,
            'discount': line.discount,
            'quantity': line.quantity,
            'uom_id': line.uom_id.id,
            'product_id': line.product_id.id,
            'invoice_line_tax_ids': [(6, 0, tax.ids)],
            'analytic_tag_ids': [(6, 0, line.analytic_account_id.tag_ids.ids)],
            'sub_account_id': line.sub_account_id.id
        }
    @api.multi
    def _recurring_create_invoice(self, automatic=False):
        auto_commit = self.env.context.get('auto_commit', True)
        cr = self.env.cr
        invoices = self.env['account.invoice']
        current_date = date.today() + timedelta(days=20)
        imd_res = self.env['ir.model.data']
        template_res = self.env['mail.template']
        if len(self) > 0:
            subscriptions = self
        else:
            domain = [('recurring_next_date', '<=', current_date),
                      ('state', 'in', ['open', 'pending'])]
            subscriptions = self.search(domain)
        if subscriptions:
            sub_data = subscriptions.read(fields=['id', 'company_id'])
            for company_id in set(data['company_id'][0] for data in sub_data):
                sub_ids = [s['id'] for s in sub_data if s['company_id'][0] == company_id]
                subs = self.with_context(company_id=company_id, force_company=company_id).browse(sub_ids)
                context_company = dict(self.env.context, company_id=company_id, force_company=company_id)
                for subscription in subs:
                    if automatic and auto_commit:
                        cr.commit()
                    # payment + invoice (only by cron)
                    if subscription.template_id.payment_mandatory and subscription.recurring_total and automatic:
                        try:
                            payment_token = subscription.payment_token_id
                            tx = None
                            if payment_token:
                                invoice_values = subscription.with_context(lang=subscription.partner_id.lang)._prepare_invoice()
                                new_invoice = self.env['account.invoice'].with_context(context_company).create(invoice_values)
                                new_invoice.message_post_with_view('mail.message_origin_link',
                                    values = {'self': new_invoice, 'origin': subscription},
                                    subtype_id = self.env.ref('mail.mt_note').id)
                                new_invoice.with_context(context_company).compute_taxes()
                                tx = subscription._do_payment(payment_token, new_invoice, two_steps_sec=False)[0]
                                # commit change as soon as we try the payment so we have a trace somewhere
                                if auto_commit:
                                    cr.commit()
                                if tx.state in ['done', 'authorized']:
                                    subscription.send_success_mail(tx, new_invoice)
                                    msg_body = 'Automatic payment succeeded. Payment reference: <a href=# data-oe-model=payment.transaction data-oe-id=%d>%s</a>; Amount: %s. Invoice <a href=# data-oe-model=account.invoice data-oe-id=%d>View Invoice</a>.' % (tx.id, tx.reference, tx.amount, new_invoice.id)
                                    subscription.message_post(body=msg_body)
                                    if auto_commit:
                                        cr.commit()
                                else:
                                    _logger.error('Fail to create recurring invoice for subscription %s', subscription.code)
                                    if auto_commit:
                                        cr.rollback()
                                    new_invoice.unlink()
                            if tx is None or tx.state != 'done':
                                amount = subscription.recurring_total
                                date_close = datetime.datetime.strptime(subscription.recurring_next_date, "%Y-%m-%d") + relativedelta(days=15)
                                close_subscription = current_date >= date_close.strftime('%Y-%m-%d')
                                email_context = self.env.context.copy()
                                email_context.update({
                                    'payment_token': subscription.payment_token_id and subscription.payment_token_id.name,
                                    'renewed': False,
                                    'total_amount': amount,
                                    'email_to': subscription.partner_id.email,
                                    'code': subscription.code,
                                    'currency': subscription.pricelist_id.currency_id.name,
                                    'date_end': subscription.date,
                                    'date_close': date_close.date()
                                })
                                if close_subscription:
                                    _, template_id = imd_res.get_object_reference('sale_subscription', 'email_payment_close')
                                    template = template_res.browse(template_id)
                                    template.with_context(email_context).send_mail(subscription.id)
                                    _logger.debug("Sending Subscription Closure Mail to %s for subscription %s and closing subscription", subscription.partner_id.email, subscription.id)
                                    msg_body = 'Automatic payment failed after multiple attempts. Subscription closed automatically.'
                                    subscription.message_post(body=msg_body)
                                else:
                                    _, template_id = imd_res.get_object_reference('sale_subscription', 'email_payment_reminder')
                                    msg_body = 'Automatic payment failed. Subscription set to "To Renew".'
                                    if (datetime.datetime.today() - datetime.datetime.strptime(subscription.recurring_next_date, '%Y-%m-%d')).days in [0, 3, 7, 14]:
                                        template = template_res.browse(template_id)
                                        template.with_context(email_context).send_mail(subscription.id)
                                        _logger.debug("Sending Payment Failure Mail to %s for subscription %s and setting subscription to pending", subscription.partner_id.email, subscription.id)
                                        msg_body += ' E-mail sent to customer.'
                                    subscription.message_post(body=msg_body)
                                subscription.write({'state': 'close' if close_subscription else 'pending'})
                            if auto_commit:
                                cr.commit()
                        except Exception:
                            if auto_commit:
                                cr.rollback()
                            # we assume that the payment is run only once a day
                            traceback_message = traceback.format_exc()
                            _logger.error(traceback_message)
                            last_tx = self.env['payment.transaction'].search([('reference', 'like', 'SUBSCRIPTION-%s-%s' % (subscription.id, datetime.date.today().strftime('%y%m%d')))], limit=1)
                            error_message = "Error during renewal of subscription %s (%s)" % (subscription.code, 'Payment recorded: %s' % last_tx.reference if last_tx and last_tx.state == 'done' else 'No payment recorded.')
                            _logger.error(error_message)

                    # invoice only
                    else:
                        try:
                            invoice_values = subscription.with_context(lang=subscription.partner_id.lang)._prepare_invoice()
                            new_invoice = self.env['account.invoice'].with_context(context_company).create(invoice_values)
                            new_invoice.message_post_with_view('mail.message_origin_link',
                                values = {'self': new_invoice, 'origin': subscription},
                                subtype_id = self.env.ref('mail.mt_note').id)
                            new_invoice.with_context(context_company).compute_taxes()
                            invoices += new_invoice
                            next_date = datetime.datetime.strptime(subscription.recurring_next_date or current_date, "%Y-%m-%d")
                            periods = {'daily': 'days', 'weekly': 'weeks', 'monthly': 'months', 'yearly': 'years'}
                            invoicing_period = relativedelta(**{periods[subscription.recurring_rule_type]: subscription.recurring_interval})
                            new_date = next_date + invoicing_period
                            subscription.write({'recurring_next_date': new_date.strftime('%Y-%m-%d')})
                            if automatic and auto_commit:
                                cr.commit()
                        except Exception:
                            if automatic and auto_commit:
                                cr.rollback()
                                _logger.exception('Fail to create recurring invoice for subscription %s', subscription.code)
                            else:
                                raise
        return invoices

class SaleSubscriptionLine(models.Model):
    _name = "sale.subscription.line"
    _description = "Subscription Line"
    _inherit = ['sale.subscription.line']
    
    sub_account_id = fields.Many2one('sub.account', string='Child Account', index=True, ondelete='cascade')
    type = fields.Selection([('sale', 'Sale'), ('lease', 'Lease')], string='Type', required=True,default='sale')
    
    @api.onchange('product_id')
    def onchange_product_id(self):
        product = self.product_id
        partner = self.analytic_account_id.partner_id
        if partner.lang:
            self.product_id.with_context(lang=partner.lang)

        name = product.name
        if product.description_sale:
            name += '\n' + product.description_sale
        self.name = name
        
    @api.depends('price_unit', 'quantity', 'discount', 'analytic_account_id.pricelist_id' , 'analytic_account_id.template_id')
    def _compute_price_subtotal(self):
        for line in self:
            line_sudo = line.sudo()
            price = line.env['account.tax']._fix_tax_included_price(line.price_unit, line_sudo.product_id.taxes_id, [])
            line.price_subtotal = line.quantity * price * (100.0 - line.discount) / 100.0 
            line.price_subtotal = line.price_subtotal * line_sudo.analytic_account_id.template_id.recurring_interval
            if line.analytic_account_id.pricelist_id:
                line.price_subtotal = line_sudo.analytic_account_id.pricelist_id.currency_id.round(line.price_subtotal)
                
    @api.onchange('product_id', 'quantity','type')
    def onchange_product_quantity(self):
        domain = {}
        subscription = self.analytic_account_id
        company_id = subscription.company_id.id
        pricelist_id = subscription.pricelist_id.id
        context = dict(self.env.context, company_id=company_id, force_company=company_id, pricelist=pricelist_id, quantity=self.quantity)
        if not self.product_id:
            self.price_unit = 0.0
            domain['uom_id'] = []
        else:
            partner = subscription.partner_id.with_context(context)
            if partner.lang:
                context.update({'lang': partner.lang})

            product = self.product_id.with_context(context)
            if self.type == 'sale' : 
                self.price_unit = product.price
            else:
                self.price_unit = product.lease_price

            if not self.uom_id:
                self.uom_id = product.uom_id.id
            if self.uom_id.id != product.uom_id.id:
                self.price_unit = product.uom_id._compute_price(self.price_unit, self.uom_id)
            domain['uom_id'] = [('category_id', '=', product.uom_id.category_id.id)]

        return {'domain': domain}

        
class EquipmentType(models.Model):
    _name = "equipment.type"
    _description = "Equipment Types"
    _order = "name"
    _inherit = ['mail.thread']

    name = fields.Char('Name', required=True, track_visibility='onchange')
    code = fields.Char('Code', required=True, track_visibility='onchange')
    active = fields.Boolean('Active', default='True')

class BrandType(models.Model):
    _name = "brand.type"
    _description = "Brand Types"
    _order = "name"
    _inherit = ['mail.thread']

    name = fields.Char('Name', required=True, track_visibility='onchange')
    code = fields.Char('Code', required=True, track_visibility='onchange')
    active = fields.Boolean('Active', default='True')

class CustomerRequest(models.Model):
    
    _name = "customer.request"
    _description = "customer request form"
    _order = "name"
    _inherit = ['res.partner']
    
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submit', 'Submitted'),
        ('approve', 'Approved'),
        ('reject', 'Rejected'),
        ], string='Status', readonly=True, index=True, copy=False, default='draft', track_visibility='onchange')

    @api.depends('is_company', 'parent_id.commercial_partner_id')
    def _compute_commercial_partner(self):
        return {}
            
          
    @api.multi
    def button_reset(self):
        self.write({'state': 'draft'})
        return {}
    
    @api.multi
    def button_submit(self):
        self.write({'state': 'submit'})
        return {}
    
    @api.multi
    def button_approve(self):
        self.write({'state': 'approve'})
        vals = {
            'name' : self.name,
            'company_type' : self.company_type,
            'image' : self.image,
            'parent_id' : self.parent_id.id,
            'street' : self.street,
            'street2' : self.street2,
            'city' : self.city,
            'state_id' : self.state_id.id,
            'zip' : self.zip,
            'country_id' : self.country_id.id,            
            'vat' : self.vat,
            'function' : self.function,
            'phone' : self.phone,
            'mobile' : self.mobile,
            'email' : self.email,
            'customer': self.customer,
            'supplier' : self.supplier
        }
        self.sudo().env['res.partner'].create(vals)
        return {}
    
    @api.multi
    def button_reject(self):
        self.write({'state': 'reject'})
        return {}
    
class SubAccount(models.Model):
        
    _name = "sub.account"
    _description = "sub account form"
    _order = "parent_id"
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    
    @api.multi
    def name_get(self):
        res = []
        for partner in self:
            result = partner.name
            if partner.child_account:
                result = str(partner.name) + " " + str(partner.child_account)
            res.append((partner.id, result))
        return res
    
    def _default_category(self):
        return self.env['res.partner.category'].browse(self._context.get('category_id'))

    def _default_company(self):
        return self.env['res.company']._company_default_get('res.partner')
            
    def _compute_company_type(self):
        for partner in self:
            partner.company_type = 'company' if partner.is_company else 'person'
            
#     def _createSub(self):
#         partner_ids = self.search([('parent_id','=',self.parent_id.id)])
#         number = len(partner_ids) + 1
#         number = "SA00" + str(number)
#         return number

    name = fields.Char(index=True, track_visibility='onchange')
    
    parent_id = fields.Many2one('res.partner', string='Customer', domain="[('customer','=',True)]", index=True, ondelete='cascade', track_visibility='onchange')
        
    function = fields.Char(string='Description')
    
    comment = fields.Text(string='Desription')
    
    addinfo = fields.Text(string='Additional Information')
    
    child_account = fields.Char(string='Child Account Number', index=True, copy=False, default='/', track_visibility='onchange')
    
    website = fields.Char(help="Website of Partner or Company")
    
    employee = fields.Boolean(help="Check this box if this contact is an Employee.")
    
    fax = fields.Char(help="fax")
    
    create_date = fields.Date(string='Create Date', readonly=True, track_visibility='onchange')
    
    activation_date = fields.Date(string='Activation Date', readonly=False, track_visibility='onchange')
    
    term_date = fields.Date(string='Termination Date', track_visibility='onchange')
    
    perm_up_date = fields.Date(string='Permanent Activation Date', readonly=False, track_visibility='onchange')
    
    contact_person = fields.Many2one('res.partner.title')
    
    company_name = fields.Many2many('Company Name')
    
    employee = fields.Boolean(help="Check this box if this contact is an Employee.")
      
    type = fields.Selection(
        [('contact', 'Contact'),
         ('invoice', 'Invoice address'),
         ('delivery', 'Shipping address'),
         ('other', 'Other address')], string='Address Type',
        default='invoice',
        help="Used to select automatically the right address according to the context in sales and purchases documents.")
    street = fields.Char()
    street2 = fields.Char()
    zip = fields.Char(change_default=True)
    city = fields.Char()
    state_id = fields.Many2one("res.country.state", string='State', ondelete='restrict')
    country_id = fields.Many2one('res.country', string='Country', ondelete='restrict')
    email = fields.Char()
    
    phone = fields.Char()
    mobile = fields.Char()
    
    company_type = fields.Selection(string='Company Type',
        selection=[('person', 'Individual'), ('company', 'Company')],
        compute='_compute_company_type', inverse='_write_company_type')
    company_id = fields.Many2one('res.company', 'Company', index=True, default=_default_company)
    
    contact_address = fields.Char(compute='_compute_contact_address', string='Complete Address')
    company_name = fields.Char('Company Name') 
    
    state = fields.Selection([
        ('new', 'Waiting Approval'),
        ('approve', 'Approved'),
        ('activate', 'Activated'),
        ('suspend', 'Suspended'),
        ('terminate', 'Terminated'),
        ('cancel', 'Canceled'),
        ('reject', 'Rejected'),
        ], string='Status', index=True, copy=False, default='new', track_visibility='onchange')

    @api.model
    def create(self, vals):
        partner_ids = self.search([('parent_id','=',vals['parent_id'])],order="child_account desc")
        for p in  partner_ids:
            print(p.child_account)
        if not partner_ids:
            vals['child_account'] = "SA001"
        else:
            number = partner_ids[0].child_account.split("A",2)
            number = int(number[1]) + 1
            vals['child_account'] = "SA" + str(number).zfill(3)
        return super(SubAccount, self).create(vals)
    
    
    #partners = self.search([len('child_account')])
     #       print(partners)
      #      partners = partners + 1
       #     label = "SA"
        #    partners = str(label) + str(partners.child_account)
        
    
    @api.multi
    def button_new(self):
        self.write({'state': 'new'})
        return {}
    
    @api.multi
    def button_activate(self):
        self.write({'state': 'activate'})
#        self.activation_date = date.today()
        return {}
    
    @api.multi
    def button_suspend(self):
        self.write({'state': 'suspend'})
        return {}
    
    @api.multi
    def button_terminate(self):
        self.write({'state': 'terminate'})
        self.term_date = date.today()
        return {}
    
    @api.multi
    def button_cancel(self):
        self.write({'state': 'cancel'})
        return {}
    
    @api.multi
    def button_approve(self):
        self.write({'state': 'approve'})
        return {}
    
    @api.multi
    def button_reject(self):
        self.write({'state': 'reject'})
        return {}

class PensionManager(models.Model):
    _name = 'pen.type'
    
    name = fields.Char(string='Name')
    contact_person = fields.Char(string='Contact person')
    phone = fields.Char(string='Phone Number')
    contact_address = fields.Text(string='Contact Address')
    pfa_id = fields.Char(string='PFA ID', required=True)
    email = fields.Char(string='Email')
    notes = fields.Text(string='Notes')
        
class NextofKin(models.Model):
    _name = 'kin.type'
        
    name = fields.Char(string='First Name', required=True)
    lname = fields.Char(string='Last Name', required=True)
    gender = fields.Selection(
        [('male', 'Male'),
         ('Female', 'Female')], string='Gender',
        default='male')
    mstatus= fields.Selection(
        [('single', 'Single'),
         ('married', 'Married'),
         ('legal', 'Legal Cohabitant'),
         ('divorced', 'Divorced'),
         ('widower', 'Widower')], string='Marital Status',
        default='single')
    email = fields.Char(string='Email')
    telphone = fields.Char(string='Telephone Number 1',required=True)
    phone_id = fields.Char(string='Telephone Number 2')  
    
                    
class Employee(models.Model):
    _inherit = 'hr.employee'

    pfa_id = fields.Char(string='PFA ID')
    pf_id = fields.Many2one('pen.type', string='Penson Fund Administrator', index=True)
    expiry_date = fields.Date(string='Passport Expiry Date', index=True)
    renewal_date = fields.Date(string='Visa Renewal Date', index=True)
    probation_period = fields.Integer(string='Probation Period',  index=True)
    serpac = fields.Char(string='SERPAC REnewal Date')
    next_ofkin = fields.One2many('kin.type', 'phone_id', string='Next of Kin')
    
           
class ProductTemplate(models.Model):
    _inherit = 'product.template'
    
    @api.depends('product_variant_ids', 'product_variant_ids.default_code', 'brand')
    def _compute_default_code(self):
        unique_variants = self.filtered(lambda template: len(template.product_variant_ids) == 1)
        for template in unique_variants:
            template.default_code = template.product_variant_ids.default_code
        for template in (self - unique_variants):
            template.default_code = ''
        
    @api.model
    def create(self, vals):
        brand = self.env['brand.type'].search([('id','=',vals['brand'])])
        equipment = self.env['equipment.type'].search([('id','=',vals['equipment_type'])])
        code = brand.code + equipment.code
#         other = self.search([('default_code','like',code + '%')],order="default_code desc")
#         if other:
#             no = int(other[0].default_code[4:8]) + 1
#         else:
#             no = 1
        
        no = self.env['ir.sequence'].next_by_code('product.template')
        item_code = code + str(no)
        vals['default_code'] = item_code
        a = super(ProductTemplate, self).create(vals)
        a.send_message()
        return a
        return super(ProductTemplate, self).create(vals)
    
    @api.multi
    def send_message(self):
        if self.billing_approval == False:
            group_id = self.env['ir.model.data'].xmlid_to_object('netcom.group_sale_billing')
            user_ids = []
            partner_ids = []
            for user in group_id.users:
                user_ids.append(user.id)
                partner_ids.append(user.partner_id.id)
            self.message_subscribe_users(user_ids=user_ids)
            subject = "Created Product {} needs Approval From Billing".format(self.name)
            self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
            return False
        return True
    
    active = fields.Boolean('Active', default=False, help="If unchecked, it will allow you to hide the product without removing it.", copy=False)
    brand = fields.Many2one('brand.type', string='Brand', track_visibility='onchange', index=True)
    equipment_type = fields.Many2one('equipment.type', string='Equipment Type', track_visibility='onchange', index=True)
    desc = fields.Text('Remarks/Description')
    lease_price = fields.Float('Lease Price')
    billing_approval = fields.Boolean('Billing Approval', readonly=True, copy=False)
    
    state = fields.Selection([
        ('approve', 'Approved'),
        ('reject', 'Rejected'),
        ], string='Status', readonly=True, copy=False, track_visibility='onchange')
    
    @api.multi
    def button_approve(self):
        self.write({'billing_approval': True})
        if self.billing_approval == True:
            subject = "Product Approved, {} can be Used now".format(self.name)
            partner_ids = []
            for partner in self.message_partner_ids:
                partner_ids.append(partner.id)
            self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
            self.write({'active': True})
            self.write({'state': 'approve'})
    
    
class ExpenseRef(models.Model):
    _name = 'hr.expense'
    _inherit = 'hr.expense'
    
    name = fields.Char('Order Reference', readonly=True, required=True, index=True, copy=False, default='New')
    description = fields.Char(string='Expense Desciption') 

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('hr.expense') or '/'
        return super(ExpenseRef, self).create(vals)
    
class ExpenseRefSheet(models.Model):
    _name = "hr.expense.sheet"
    _inherit = 'hr.expense.sheet'
    
    name = fields.Char(string='Expense Report Summary', readonly=True, required=True)
    description = fields.Char(string='Expense Desciption', readonly=True, compute='get_desc')
    
    @api.one
    def get_desc(self):
        for expense in self.expense_line_ids:
            if expense.description:
                self.description = expense.description
                break
    
class JournalMailThread(models.Model):
    _name = "account.move"
    _inherit = ['account.move','mail.thread', 'mail.activity.mixin', 'portal.mixin']
    
    @api.multi
    def _get_default_journal(self):
        if self.env.context.get('default_journal_type'):
            return self.env['account.journal'].search([('company_id', '=', self.env.user.company_id.id), ('type', '=', self.env.context['default_journal_type'])], limit=1).id

    
    name = fields.Char(string='Number', required=True, copy=False, default='/', track_visibility='onchange')
    ref = fields.Char(string='Reference', copy=False, track_visibility='onchange')
    date = fields.Date(required=True, states={'posted': [('readonly', True)]}, index=True, default=fields.Date.context_today, track_visibility='onchange')
    journal_id = fields.Many2one('account.journal', string='Journal', required=True, states={'posted': [('readonly', True)]}, default=_get_default_journal, track_visibility='onchange')
    currency_id = fields.Many2one('res.currency', compute='_compute_currency', store=True, string="Currency", track_visibility='onchange')
    state = fields.Selection([('draft', 'Unposted'), ('posted', 'Posted')], string='Status',
      required=True, readonly=True, copy=False, default='draft',
      help='All manually created new journal entries are usually in the status \'Unposted\', '
           'but you can set the option to skip that status on the related journal. '
           'In that case, they will behave as journal entries automatically created by the '
           'system on document validation (invoices, bank statements...) and will be created '
           'in \'Posted\' status.', track_visibility='onchange')
    line_ids = fields.One2many('account.move.line', 'move_id', string='Journal Items',
        states={'posted': [('readonly', True)]}, copy=True, track_visibility='onchange')
    partner_id = fields.Many2one('res.partner', compute='_compute_partner_id', string="Partner", store=True, readonly=True, track_visibility='onchange')
    amount = fields.Monetary(compute='_amount_compute', store=True, track_visibility='onchange')
    narration = fields.Text(string='Internal Note', track_visibility='onchange')
    company_id = fields.Many2one('res.company', related='journal_id.company_id', string='Company', store=True, readonly=True,
        default=lambda self: self.env.user.company_id, track_visibility='onchange')
    matched_percentage = fields.Float('Percentage Matched', compute='_compute_matched_percentage', digits=0, store=True, readonly=True, help="Technical field used in cash basis method", track_visibility='onchange')
    # Dummy Account field to search on account.move by account_id
    dummy_account_id = fields.Many2one('account.account', related='line_ids.account_id', string='Account', store=False, readonly=True, track_visibility='onchange')
    tax_cash_basis_rec_id = fields.Many2one(
        'account.partial.reconcile',
        string='Tax Cash Basis Entry of',
        help="Technical field used to keep track of the tax cash basis reconciliation. "
        "This is needed when cancelling the source: it will post the inverse journal entry to cancel that part too.", track_visibility='onchange')
    
class StoreReqEdit(models.Model):
    _name = "stock.picking"
    _inherit = 'stock.picking'
    
    location_id = fields.Many2one(
        'stock.location', "Source Location",
        default=lambda self: self.env['stock.picking.type'].browse(self._context.get('default_picking_type_id')).default_location_src_id,
        readonly=False, required=True,
        states={'draft': [('readonly', False)]})
    location_dest_id = fields.Many2one(
        'stock.location', "Destination Location",
        default=lambda self: self.env['stock.picking.type'].browse(self._context.get('default_picking_type_id')).default_location_dest_id,
        readonly=True, required=True,
        states={'draft': [('readonly', False)]})
'''
class RepairSub(models.Model):
    _name = 'mrp.repair'
    _inherit = 'mrp.repair'
     
    parent_id = fields.Many2one('res.partner', string='Customer', domain="[('customer','=',True)]", index=True, ondelete='cascade', track_visibility='onchange')
    sub_account_id = fields.Many2one('sub.account', string='Sub Account', index=True, ondelete='cascade')
'''
class Holidays(models.Model):
    _name = "hr.holidays"
    _inherit = 'hr.holidays'
    
    state = fields.Selection([
            ('draft', 'To Submit'),
            ('cancel', 'Cancelled'),
            ('confirm', 'To Approve'),
            ('refuse', 'Refused'),
            ('validate1', 'Second Approval'),
            ('validate', 'Approved')
            ], string='Status', readonly=False, track_visibility='onchange', copy=False, default='confirm',
                help="The status is set to 'To Submit', when a leave request is created." +
                "\nThe status is 'To Approve', when leave request is confirmed by user." +
                "\nThe status is 'Refused', when leave request is refused by manager." +
                "\nThe status is 'Approved', when leave request is approved by manager.")
    
    date_from = fields.Date('Start Date', readonly=True, index=True, copy=False,
        states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]}, track_visibility='onchange')
    date_to = fields.Date('End Date', readonly=True, copy=False,
        states={'draft': [('readonly', False)], 'confirm': [('readonly', False)]}, track_visibility='onchange')
    
    @api.model
    def create(self, vals):
        result = super(Holidays, self).create(vals)
        result.send_mail()
        return result
    
    def send_mail(self):
        if self.state in ['confirm']:
            config = self.env['mail.template'].sudo().search([('name','=','Leave Approval Request Template')], limit=1)
            mail_obj = self.env['mail.mail']
            if config:
                values = config.generate_email(self.id)
                mail = mail_obj.create(values)
                if mail:
                    mail.send()
    
    
class HolidaysType(models.Model):
    _name = "hr.holidays.status"
    _inherit = 'hr.holidays.status'

    remaining_leaves = fields.Float(compute='_compute_leaves', string='Remaining Leaves',
        help='Maximum Leaves Allowed - Leaves Already Taken', track_visibility='onchange')
    
class stockmoveManorder(models.Model):
    _inherit = "stock.move"

    cost = fields.Float(string='Cost', related="product_tmpl_id.standard_price", track_visibility='onchange', copy=False, readonly=True)
    
class ManOrder(models.Model):
    _inherit = "mrp.production"
    
    need_override = fields.Boolean ('Need Billing Override?', compute='_check_override')
    
    override_done = fields.Boolean ('Override Done?', track_visibility="onchange", store=True)
        
    initial_cost = fields.Float(string='Initial Cost', readonly=True)
    
    total_cost = fields.Float(string='Total Cost', compute='_total_cost', track_visibility='onchange', readonly=True)
    
    state = fields.Selection([
        ('confirmed', 'Confirmed'),
        ('ready_for_production', 'Ready for Production'),
        ('planned', 'Planned'),
        ('progress', 'In Progress'),
        ('done', 'Done'),
        ('cancel', 'Cancelled')], string='State',
        copy=False, default='confirmed', track_visibility='onchange')
    
    @api.multi
    def button_ready(self):
        self.write({'state': 'ready_for_production'})
        if self.state in ['ready_for_production']:
            group_id = self.env['ir.model.data'].xmlid_to_object('stock.group_stock_manager')
            user_ids = []
            partner_ids = []
            for user in group_id.users:
                user_ids.append(user.id)
                partner_ids.append(user.partner_id.id)
            self.message_subscribe_users(user_ids=user_ids)
            subject = "Manufacturing Order {} is Ready for Production".format(self.name)
            self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
            return False
        return True
    
    @api.model
    def create(self, values):
        a = super(ManOrder, self).create(values)
        for record in a.move_raw_ids:
            a.initial_cost += record.cost * record.product_uom_qty
        return a
    
    @api.multi
    def _check_override(self):
        for self in self:
            if self.total_cost > self.initial_cost and self.override_done == False:
                self.need_override = True
            else:
                self.need_override = False
    
    @api.multi    
    @api.depends('move_raw_ids.product_uom_qty')
    def _total_cost(self):
        for a in self:
            for line in a.move_raw_ids:
                a.total_cost += line.cost * line.product_uom_qty
    
    @api.multi
    def request_approval(self):
        if self.total_cost > self.initial_cost and self.override_done == False:
            self.need_override = True
            group_id = self.env['ir.model.data'].xmlid_to_object('netcom.group_sale_billing')
            user_ids = []
            partner_ids = []
            for user in group_id.users:
                user_ids.append(user.id)
                partner_ids.append(user.partner_id.id)
            self.message_subscribe_users(user_ids=user_ids)
            subject = "Manufacturing Order {} needs a cost override".format(self.name)
            self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
            return False
    
    @api.multi
    def open_produce_product(self):
        if self.total_cost > self.initial_cost and self.override_done == False:
            self.need_override = True
            group_id = self.env['ir.model.data'].xmlid_to_object('netcom.group_sale_billing')
            user_ids = []
            partner_ids = []
            for user in group_id.users:
                user_ids.append(user.id)
                partner_ids.append(user.partner_id.id)
            self.message_subscribe_users(user_ids=user_ids)
            subject = "Manufacturing Order {} needs a cost override".format(self.name)
            self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
            return False
        self.ensure_one()
        action = self.env.ref('mrp.act_mrp_product_produce').read()[0]
        return action
    
    @api.multi
    def action_override_budget(self):
        self.write({'override_done': True})
        if self.need_override == True:
            subject = "Cost Override Done, Manufacturing Order {} can be Produced now".format(self.name)
            partner_ids = []
            for partner in self.message_partner_ids:
                partner_ids.append(partner.id)
            self.message_post(subject=subject,body=subject,partner_ids=partner_ids)
            self.write({'need_override': False})

class NetcomMrpProductProduce(models.TransientModel):
    _name = "mrp.product.produce"
    _inherit = "mrp.product.produce"
    
    @api.multi
    def do_produce(self):
        # Nothing to do for lots since values are created using default data (stock.move.lots)
        quantity = self.product_qty
        if float_compare(quantity, 0, precision_rounding=self.product_uom_id.rounding) <= 0:
            raise UserError(_("The production order for '%s' has no quantity specified") % self.product_id.display_name)
        for move in self.production_id.move_raw_ids:
            # TODO currently not possible to guess if the user updated quantity by hand or automatically by the produce wizard.
            if move.product_id.tracking == 'none' and move.state not in ('done', 'cancel') and move.unit_factor:
                rounding = move.product_uom.rounding
                if self.product_id.tracking != 'none':
                    qty_to_add = float_round(quantity * move.unit_factor, precision_rounding=rounding)
                    move._generate_consumed_move_line(qty_to_add, self.lot_id)
                else:
                    move.quantity_done += float_round(quantity * move.unit_factor, precision_rounding=rounding)
        for move in self.production_id.move_finished_ids:
            if move.product_id.tracking == 'none' and move.state not in ('done', 'cancel'):
                rounding = move.product_uom.rounding
                if move.product_id.id == self.production_id.product_id.id:
                    move.quantity_done += float_round(quantity, precision_rounding=rounding)
                elif move.unit_factor:
                    # byproducts handling
                    move.quantity_done += float_round(quantity * move.unit_factor, precision_rounding=rounding)
        self.check_finished_move_lots()
        if self.production_id.state == 'confirmed' or self.production_id.state == 'ready_for_production':
            self.production_id.write({
                'state': 'progress',
                'date_start': datetime.now(),
            })
        return {'type': 'ir.actions.act_window_close'}

class Hrrecruitment(models.Model):
    _inherit = 'hr.applicant'

    name = fields.Char(string='Application ID')

    #partner_name = fields.Char(string='Full Name', required=1)
    applicant_image = fields.Binary(string="Applicant Passport", attachment=True, store=True, help="This field holds the applicant's passport image")
    preferred_name = fields.Char(string='Preferred Name')
    gender = fields.Selection([('male', 'Male'), ('female', 'Female')], string='Gender')
    date_of_birth = fields.Char(string='Date of Birth')
    nationality = fields.Many2one('res.country', string='Nationality')
    current_location = fields.Char(string='Current Location')
    preferred_location = fields.Char(string='Preferred Location')
    current_salary = fields.Char(string='Current Salary')
    salary_expected = fields.Char("Expected Salary", help="Salary Expected by Applicant")

    family_status = fields.Selection([('single', 'Single'), ('married', 'Married'), ('divorced','Divorced')], string='Family Status')
    
    longest_employed = fields.Selection([('1','1'), ('2','2'),('3','3'), ('4','4'),('5','5'), ('6','6'),('7','7'), ('8','8'),('9','9'), ('10','10'),('11','11'), ('12','12'),('13','13'), ('14','14'),('15_and_above','15 and Above')], 
                                        string='Longest duration as an Employee')
    num_employment_10yrs = fields.Selection([('1','1'), ('2','2'),('3','3'), ('4','4'),('5','5'), ('6','6'),('7','7'), ('8','8'),('9','9'), ('10','10'),('11','11'), ('12','12'),('13','13'), ('14','14'),('15_and_above','15 and Above')], 
                                        string='Number of jobs held in the last 10 years')
    reason_for_career_change = fields.Char(string='Reason for current career change')
    reason_for_leaving = fields.Char(string='Reasons for leaving each employer in the last 10 years')
    employment_status = fields.Selection([('employed','Employed'), ('unemployed','Unemployed')], string='Employment status')
    willingness_to_relocate = fields.Selection([('yes','Yes'), ('no','No')], string='Willingness to Relocate')
    
    commercial_exp = fields.Selection([('1','1'), ('2','2'),('3','3'), ('4','4'),('5','5'), ('6','6'),('7','7'), ('8','8'),('9','9'), ('10','10'),('11','11'), ('12','12'),('13','13'), ('14','14'),('15_and_above','15 and Above')], 
                                        string='Total years commercial experience')
    
    industry_exp = fields.Char(string='Key Industry/Sector Experience')
    country_exp = fields.Char(string='International/Country Experience')
    highest_level_edu = fields.Selection([('ond','OND'), ('hnd','HND'), ('bsc','BSc'), ('msc','MSc'), ('above','Above')], string='Highest Level of Education')
    professional_cert = fields.Char(string='Professional Certification(s)/Affiliation(s)')
    notice_period = fields.Char(string='Notice Period')
    skype_id = fields.Char(string='Skype ID')
    last_3_employers = fields.Char(string='Last three(3) employers')

#    cover_letter = fields.Binary(string="Cover Letter", attachment=True, store=True, help="This field holds the applicant's cover letter")
#    certificates = fields.Binary(string="Certificate(s)", attachment=True, store=True, help="This field holds the applicant's certificates")
#    other_attachments = fields.Binary(string="Other(s)", attachment=True, store=True, help="This field holds any other attachments the applicant may want to present")
    
    
#     name = fields.Char()
#     value = fields.Integer()
#     value2 = fields.Float(compute="_value_pc", store=True)
#     description = fields.Text()
#
#     @api.depends('value')
#     def _value_pc(self):
#         self.value2 = float(self.value) / 100
