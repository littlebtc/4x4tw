$( function() {
  $('#form').submit( function() {
    $('#submit').attr('disabled', 'true');
  });
  $('#submit').attr('disabled', '');
}
);

