// Copyright (c) 2026, Impact Analyser and contributors
// For license information, please see license.txt

frappe.ui.form.on('Dead Code Eliminator', {
	onload: function(frm) {
		if (!frm.doc.target_app) {
			frm.set_value('target_app', 'impact_analyser');
		}
	},

	refresh: function(frm) {
		// Primary Action Button: Scan Entire App
		frm.add_custom_button(__('⚡ Scan Entire App'), function() {
			const appName = frm.doc.target_app || 'impact_analyser';

			frappe.show_alert({
				message: __('Traversing all DocTypes, .py, and .js files in ' + appName + '...'),
				indicator: 'blue'
			});

			frm.call({
				doc: frm.doc,
				method: 'run_analysis',
				freeze: true,
				freeze_message: __('Building Global Reference Graph & Enforcing Frappe Guardrails...'),
				callback: function(r) {
					if (!r.exc && r.message) {
						frappe.show_alert({
							message: __(
								'Scan Finished! ' + r.message.total_files + ' files scanned, ' +
								r.message.total_dead_items + ' dead symbols identified across ' +
								r.message.diff_files + ' files.'
							),
							indicator: 'green'
						});
						frm.refresh();
					}
				}
			});
		}).addClass('btn-primary');

		// Filter Buttons for Inventory Table
		if (frm.doc.inventory && frm.doc.inventory.length > 0) {
			frm.add_custom_button(__('Show Low Risk Only'), function() {
				frm.fields_dict['inventory'].grid.filter('risk_level', '=', 'Low');
			}, __('Filter Results'));

			frm.add_custom_button(__('Show All'), function() {
				frm.fields_dict['inventory'].grid.clear_filter();
			}, __('Filter Results'));
		}
	}
});
