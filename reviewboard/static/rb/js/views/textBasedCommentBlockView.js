RB.TextBasedCommentBlockView = RB.AbstractCommentBlockView.extend({
    className: 'selection',

    renderContent: function() {
        this._$flag = $('<div/>')
            .addClass('selection-flag')
            .appendTo(this.$el);

        this.model.on('change:count', this._updateCount, this);
        this._updateCount();
    },

    /*
     * Updates the displayed count of comments.
     */
    _updateCount: function() {
        this._$flag.text(this.model.get('count'));
    }
});
