RB.TextBasedCommentBlockView = RB.AbstractCommentBlockView.extend({
    className: 'selection',

<<<<<<< HEAD
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

    positionCommentDlg: function(commentDlg) {
        commentDlg.positionToSide(this._$ghostCommentFlag, {
            side: 'r',
            fitOnScreen: true
        });
    },

    _updateCount: function() {
        this._$count.text(this.model.get('count'));
    }
=======
    initialize: function() {
        console.log('initialize in textbasecommentblockview');
    },

    renderContent: function() {
        console.log('render content in textbasedcommentblockview');

        this._$flag = $('<div/>')
            .addClass('selection-flag')
            .appendTo(this.$el);
    },

    positionCommentDlg: function(commentDlg) {
        commentDlg.positionToSide(this._$flag, {
            side: 'b',
            fitOnScreen: true
        });
    },
>>>>>>> d1142b9... Introduce "text-based comment block" for commenting
});
