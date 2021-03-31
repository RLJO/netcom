
import requests
import xmlrpc.client

from odoo import api, models, fields, _

url = 'https://netcomafrica-dev-2314377.dev.odoo.com'
db = 'netcomafrica-dev-2314377'
username = 'admin'
password = 'admin'

common = xmlrpc.client.ServerProxy('{}/xmlrpc/2/common'.format(url))
uid = common.authenticate(db, username, password, {})

mymodels = xmlrpc.client.ServerProxy('{}/xmlrpc/2/object'.format(url))

module = 'account.asset.depreciation.line'
limit = 200000

#attachments = mymodels.execute_kw(db, uid, password, 'ir.attachment', 'search', [[['res_model', '=', 'purchase.order']]], {'limit': 500})
#attachments_data = mymodels.execute_kw(db, uid, password, 'ir.attachment', 'read', [attachments], {'fields': ['id', 'datas', 'name', 'type', 'website_url']})

#to be used only once

class AssetDepreciationLine(models.Model):
    _inherit = 'account.asset.depreciation.line'
    
    def get_attachments(self):
        ids = [3177,3147,3649,3164,3156,3146,3157,3166,7782,3198,3178,3217,3161,3190,3182,3209,3154,3169,3186,3251,6422,4711,3201,3851,5284,7039,3173,3213,4196,3180,3220,4503,7823,3176,4328,7779,3794,5031,3196,3647,6852,3193,5009,3184,3223,4640,6362,3188,3564,4812,3211,4130,5652,3207,5564,7437,3891,3204,5472,7320,3250,5900,7510,4327,6021,7778,6990,6851,4639,6361,3554,5617,7505,4128,5471,3815,3153,3200,3160,3192,3206,3203,3151,3172,3179,3195,3159,3191,3158,3185,3252,6472,4707,3199,3813,5145,3212,4197,5902,7632,3149,3219,4504,6128,3175,3215,4343,6024,7781,3793,5130,6862,3162,3648,6853,5006,3150,3183,3222,4642,6365,3187,3565,3572,4814,6502,3168,3210,4131,5671,3205,5571,3985,3202,5473,5285,7825,6023,6991,6364,4813,6501,7507,4123,5570]
        attachments = mymodels.execute_kw(db, uid, password, 'account.asset.depreciation.line', 'search', [[['move_check', '=', False], ['asset_id', 'in', ids]]], {'limit': limit})
        attachments_data = mymodels.execute_kw(db, uid, password, 'account.asset.depreciation.line', 'read', [attachments], {'fields': ['asset_id', 'depreciated_value', 'depreciation_date', 'name', 'amount', 'remaining_value', 'sequence']})

        for d in attachments_data:
            name = d['name']
            asset_id = d['asset_id'][0]
            depreciated_value = d['depreciated_value']
            depreciation_date = d['depreciation_date']
            remaining_value = d['remaining_value']
            sequence = d['sequence']
            amount = d['amount']

            vals= {
            'name': name,
            'amount': amount,
            'asset_id': asset_id,
            'depreciated_value': depreciated_value,
            'depreciation_date': depreciation_date,
            'remaining_value': remaining_value,
            'sequence': sequence,
            }
            model2_obj= self.env['account.asset.depreciation.line']
            model2_obj.create(vals)


        
                
                