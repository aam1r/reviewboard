RB.TextBasedCommentBlockView = RB.AbstractCommentBlockView.extend({
    className: 'selection',

    renderContent: function() {
        this._$ghostCommentFlag = $("<span/>")
            .addClass("commentflag")
            .append($("<span/>").addClass("commentflag-shadow"));

        this._$innerFlag = $("<span/>")
            .addClass("commentflag-inner")
            .appendTo(this._$ghostCommentFlag);

        this._$count = $("<span/>")
            .appendTo(this._$innerFlag);

        this.$el.append(this._$ghostCommentFlag);

        this.model.on('change:count', this._updateCount, this);
        this._updateCount();
    },

    _updateCount: function() {
        this._$count.text(this.model.get('count'));
    }
});
