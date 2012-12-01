RB.TextBasedCommentBlockView = RB.AbstractCommentBlockView.extend({
    className: 'selection',

    renderContent: function() {
        this._$flag = $('<div/>')
            .addClass('selection-flag')
            .appendTo(this.$el);
    }
});
