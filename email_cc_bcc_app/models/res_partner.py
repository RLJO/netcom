# -*- coding: utf-8 -*-

import logging

from odoo.tools.misc import split_every
from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class Partner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def _notify_send(self, body, subject, recipients, **mail_values):
        emails = self.env['mail.mail']
        recipients_nbr = len(recipients)
        for email_chunk in split_every(50, recipients.ids):
            # TDE FIXME: missing message parameter. So we will find mail_message_id
            # in the mail_values and browse it. It should already be in the
            # cache so should not impact performances.
            mail_message_id = mail_values.get('mail_message_id')
            message = self.env['mail.message'].browse(mail_message_id) if mail_message_id else None
            if message and message.model and message.res_id and message.model in self.env and hasattr(self.env[message.model], 'message_get_recipient_values'):
                tig = self.env[message.model].browse(message.res_id)
                recipient_values = tig.message_get_recipient_values(notif_message=message, recipient_ids=email_chunk)
            else:
                recipient_values = self.env['mail.thread'].message_get_recipient_values(notif_message=None, recipient_ids=email_chunk)
            create_values = {
                'body_html': body,
                'subject': subject,
                'cc_visible': message.cc_visible,
                'bcc_visible': message.bcc_visible,
            }
            # Set Partner CC & BCC Value In Recipient CC & BCC
            if message.cc_visible:
                create_values.update({'recipient_cc_ids': [(4, pccid.id) for pccid in message.partner_cc_ids]})
            else:
                create_values.update({'recipient_cc_ids': []})

            if message.bcc_visible:
                create_values.update({'recipient_bcc_ids': [(4, pbccid.id) for pbccid in message.partner_bcc_ids]})
            else:
                create_values.update({'recipient_bcc_ids': []})

            create_values.update(mail_values)
            create_values.update(recipient_values)
            emails |= self.env['mail.mail'].create(create_values)
        return emails, recipients_nbr

