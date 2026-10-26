//! Offline CECD read semantics when no StreetPass mailbox has been supplied.
//! Empty storage is a NoData result, never a successful fabricated message.
use crate::{kernel::ipc::{CommandBuffer,Header},System};
use zakuro_common::result::{Level,Module,ResultCode,Summary};

pub const NO_DATA:u32=ResultCode::new(Level::Status,Summary::NotFound,Module::Cec,1007).0;
pub const NOT_AUTHORIZED:u32=ResultCode::new(Level::Status,Summary::NotFound,Module::Cec,1002).0;

pub fn handle(system:&mut System,buffer:&CommandBuffer,header:Header)->bool {
    if header.command_id()!=0x0012 {return false;}
    let invalid=ResultCode::new(Level::Usage,Summary::InvalidArgument,Module::Cec,1004).0;
    if header.normal_params()!=4 || header.translate_params()!=4 {
        buffer.reply_error(&mut system.memory,0x0012,invalid);
        return true;
    }
    let size=buffer.get(&mut system.memory,1);
    let path_type=buffer.get(&mut system.memory,3);
    let descriptor=buffer.get(&mut system.memory,7);
    let address=buffer.get(&mut system.memory,8);
    let result=if size>1024*1024 || descriptor>>4<size || !matches!(descriptor&15,0xc|0xe) {
        invalid
    } else if matches!(path_type,10..=13) {
        NOT_AUTHORIZED
    } else if matches!(path_type,1..=7|100..=199) {
        NO_DATA
    } else {
        ResultCode::new(Level::Usage,Summary::InvalidArgument,Module::Cec,1005).0
    };
    buffer.set(&mut system.memory,0,Header::new(0x0012,2,2).0);
    buffer.set(&mut system.memory,1,result);
    buffer.set(&mut system.memory,2,0);
    buffer.set(&mut system.memory,3,descriptor);
    buffer.set(&mut system.memory,4,address);
    true
}
