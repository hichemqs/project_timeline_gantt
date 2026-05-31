# -*- coding: utf-8 -*-
{
    'name': 'Project Timeline Gantt',
    'version': '19.0.1.0.0',
    'category': 'Project',
    'summary': 'Unified Gantt timeline aggregating Purchase, Sales and Manufacturing orders',
    'description': """
        Provides a single Gantt planning view that consolidates records from:
        - Purchase Orders
        - Sales Orders
        - Manufacturing Orders

        Designed to be extended with additional business objects without
        modifying core module logic.
    """,
    'author': 'Your Company',
    'website': 'https://yourcompany.com',
    'license': 'OEEL-1',

    'depends': [
        'project',
        'purchase',
        'sale_management',
        'mrp',
        'web_gantt',          # Odoo 19 Enterprise Gantt widget
    ],

    'data': [
        # Security first
        'security/ir.model.access.csv',

        # Model views
        'views/project_timeline_views.xml',
        'views/project_timeline_gantt.xml',
        'views/project_timeline_menus.xml',
    ],

    'assets': {
        # Future JS overrides for click-to-source behavior can be added here
        'web.assets_backend': [],
    },

    'installable': True,
    'application': True,
    'auto_install': False,
}
